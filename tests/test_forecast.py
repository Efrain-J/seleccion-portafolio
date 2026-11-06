import numpy as np
import pandas as pd
import pytest
from model_helpers import make_model_cfg, synthetic_betas, synthetic_uvr

from uvr_loan.config import ROOT, load_assumptions
from uvr_loan.inflation_model.cpi import UVR_LAG_MONTHS
from uvr_loan.inflation_model.forecast import (
    build_history,
    corrected_distribution,
    generate_forecasts,
    sample_at_horizon,
    save_forecasts,
    simulate_origin,
)
from uvr_loan.inflation_model.hull_white import simulate_hull_white

ORIGINS = list(pd.period_range("2016-01", "2017-12", freq="M"))
FIRST_FORECAST = pd.Period("2017-08", "M")  # 12 realised errors are needed before the first forecast


def history_table(n=60) -> pd.DataFrame:
    """History with a realised inflation ~1 pp above the model's centre."""
    rng = np.random.default_rng(3)
    centre = 0.04 + 0.002 * rng.standard_normal(n)
    seasonal = 0.001 * np.sin(np.arange(n))
    realised = centre + 0.01 + seasonal + 0.01 * rng.standard_normal(n)
    index = pd.period_range("2014-01", periods=n, freq="M")
    return pd.DataFrame(
        {"realised": realised, "breakeven_1y": centre, "hw_mean": centre, "seasonal": seasonal}, index=index
    )


@pytest.fixture(scope="module")
def forecasts():
    return generate_forecasts(synthetic_betas(), synthetic_uvr(), make_model_cfg(), ORIGINS)


def test_sample_is_selected_by_time():
    tenors = np.arange(1, 11)
    out = simulate_hull_white(5, (0.11, 0.13), tenors, np.full(10, 0.005), np.full(10, 0.05), 12, 1, 30, 1)
    pd.testing.assert_series_equal(sample_at_horizon(out, 6), out["spot_rates"].iloc[:, 5])
    pd.testing.assert_series_equal(sample_at_horizon(out, 12), out["spot_rates"].iloc[:, 11])


def test_simulate_origin_returns_a_sample_and_the_one_year_breakeven():
    sample, breakeven = simulate_origin(synthetic_betas(), pd.Timestamp("2017-06-30"), make_model_cfg())
    assert len(sample) == 200
    assert np.isfinite(sample).all()
    assert 0 < breakeven < 0.2


def test_simulate_origin_ignores_betas_after_the_cutoff():
    cutoff = pd.Timestamp("2017-06-30")
    altered = synthetic_betas()
    altered.loc[altered["date"] > cutoff, ["beta0_cop", "beta0_uvr"]] += 3.0
    cfg = make_model_cfg()
    np.testing.assert_allclose(
        simulate_origin(altered, cutoff, cfg)[0], simulate_origin(synthetic_betas(), cutoff, cfg)[0]
    )


def test_history_has_nan_for_origins_whose_target_is_not_realised_yet():
    history, sims = build_history(synthetic_betas(), synthetic_uvr(), make_model_cfg(), ORIGINS)
    assert list(history.columns) == ["realised", "breakeven_1y", "hw_mean", "seasonal"]
    assert np.isnan(history.loc[ORIGINS[-1], "realised"])
    assert not np.isnan(history.loc[ORIGINS[0], "realised"])
    assert history[["breakeven_1y", "hw_mean", "seasonal"]].notna().all().all()
    assert set(sims) == set(ORIGINS)


def test_corrected_distribution_uses_only_realised_errors():
    history, cfg = history_table(), make_model_cfg()
    sims = np.random.default_rng(1).normal(0.04, 0.005, 400)
    origin = history.index[40]
    future = history.copy()
    lag = cfg["inflation_model"]["horizon_months"] + UVR_LAG_MONTHS
    future.loc[future.index > origin - lag, "realised"] += 0.2
    np.testing.assert_allclose(
        corrected_distribution(history, sims, origin, cfg), corrected_distribution(future, sims, origin, cfg)
    )


def test_corrected_distribution_shifts_by_the_historical_bias():
    history, cfg = history_table(), make_model_cfg()
    sims = np.random.default_rng(1).normal(history["hw_mean"].iloc[40], 0.005, 400)
    corrected = corrected_distribution(history, sims, history.index[40], cfg)
    assert np.median(corrected) > np.median(sims) + 0.005  # realised was ~1 pp above the centre


def test_corrected_distribution_needs_enough_history():
    history, cfg = history_table(), make_model_cfg()
    with pytest.raises(ValueError, match="history"):
        corrected_distribution(history, np.zeros(10), history.index[10], cfg)


def test_forecast_columns_and_months(forecasts):
    assert list(forecasts.columns) == ["p05_ea", "median_ea", "p995_ea", "mean_ea", "breakeven_1y_ea"]
    assert forecasts.index.name == "month"
    assert list(forecasts.index) == [str(p) for p in ORIGINS if p >= FIRST_FORECAST]


def test_forecast_percentiles_are_ordered_and_values_are_finite(forecasts):
    assert np.isfinite(forecasts.to_numpy()).all()
    assert (forecasts["p05_ea"] < forecasts["median_ea"]).all()
    assert (forecasts["median_ea"] < forecasts["p995_ea"]).all()


def test_forecasts_do_not_look_ahead(forecasts):
    cutoff = ORIGINS[21]  # 2017-10
    end = cutoff.to_timestamp(how="end").normalize()
    betas, uvr = synthetic_betas(), synthetic_uvr()
    betas.loc[betas["date"] > end, ["beta0_cop", "beta0_uvr"]] += 3.0
    uvr.loc[uvr.index > end] *= 1.5
    altered = generate_forecasts(betas, uvr, make_model_cfg(), ORIGINS)
    months = [str(p) for p in ORIGINS if FIRST_FORECAST <= p <= cutoff]
    pd.testing.assert_frame_equal(forecasts.loc[months], altered.loc[months])


def test_save_forecasts_round_trip(tmp_path, forecasts):
    path = tmp_path / "nested" / "f.csv"
    save_forecasts(forecasts, path)
    loaded = pd.read_csv(path, sep=";", index_col="month")
    pd.testing.assert_frame_equal(loaded, forecasts, check_index_type=False)


def test_reproduces_the_committed_forecast_file():
    """Golden check on real data: the model must give the numbers of data/forecasts/hw_inflation_forecasts.csv."""
    from uvr_loan.data.sources import load_uvr
    from uvr_loan.inflation_model.nelson_siegel import load_betas

    cfg = load_assumptions()
    committed = ROOT / cfg["inflation_scenarios"]["forecast_file"]
    if not (ROOT / cfg["inflation_model"]["betas_file"]).exists():
        pytest.skip("The betas file is not in data/raw/ (see data/SOURCES.md)")
    expected = pd.read_csv(committed, sep=";", index_col="month")
    result = generate_forecasts(load_betas(cfg), load_uvr(cfg), cfg)
    pd.testing.assert_frame_equal(result, expected, check_exact=False, atol=1e-10, rtol=0)

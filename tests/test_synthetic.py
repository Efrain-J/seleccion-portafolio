import numpy as np
import pandas as pd
import pytest
from helpers import make_cfg, make_panel, make_schedule

from uvr_loan.backtest import run_backtest
from uvr_loan.synthetic import (
    METRICS,
    PLANS,
    synthetic_panels,
    synthetic_path,
    synthetic_summary,
    with_prices,
)

T0 = pd.Period("2020-01", "M")
ZERO = np.zeros(24)


def synthetic_cfg(horizon=24, sigma_ea=0.15, scenarios=None):
    cfg = make_cfg(horizon=horizon)
    cfg["synthetic_etfs"] = {
        "seed": 1,
        "sigma_ea": sigma_ea,
        "scenarios": scenarios
        or {
            "both_down": {"icolcap": {"drift_ea": -0.15}, "cspx": {"drift_ea": -0.15}},
            "diverge": {"icolcap": {"drift_ea": 0.15}, "cspx": {"drift_ea": -0.15}},
        },
    }
    return cfg


def test_path_has_one_price_per_month_and_starts_at_p0():
    path = synthetic_path(50.0, 24, np.ones(24), drift_ea=0.1, sigma_ea=0.2)
    assert len(path) == 25
    assert path[0] == 50.0


def test_drift_only_grows_at_the_log_drift():
    path = synthetic_path(100.0, 24, ZERO, drift_ea=0.10, sigma_ea=0.15)
    assert path[-1] == pytest.approx(100 * np.exp(0.10 * 2))


def test_sine_returns_to_p0_after_one_period():
    path = synthetic_path(100.0, 24, ZERO, drift_ea=0.0, sigma_ea=0.0, amplitude=0.25, period_months=12)
    assert path[12] == pytest.approx(100.0)
    assert path[3] == pytest.approx(100 * np.exp(0.25))  # peak at a quarter of the period


def test_crash_multiplies_the_price_from_its_month_on():
    path = synthetic_path(100.0, 24, ZERO, drift_ea=0.0, sigma_ea=0.0, crash_month=5, crash_fall=0.4)
    assert path[:5] == pytest.approx([100.0] * 5)
    assert path[5:] == pytest.approx([60.0] * 20)


def test_noise_is_scaled_by_sigma_as_brownian_motion():
    noise = np.ones(24)
    path = synthetic_path(100.0, 24, noise, drift_ea=0.0, sigma_ea=0.2)
    assert np.log(path[12] / 100) == pytest.approx(0.2 * 12 * np.sqrt(1 / 12))


@pytest.mark.parametrize(
    "kwargs",
    [{"crash_month": 3, "crash_fall": 1.0}, {"crash_month": 3, "crash_fall": -0.1}, {"sigma_ea": -0.1}],
    ids=["fall-100%", "negative-fall", "negative-sigma"],
)
def test_invalid_parameters_raise(kwargs):
    params = {"drift_ea": 0.0, "sigma_ea": 0.1} | kwargs
    with pytest.raises(ValueError):
        synthetic_path(100.0, 24, ZERO, **params)


def test_noise_of_the_wrong_length_raises():
    with pytest.raises(ValueError, match="noise"):
        synthetic_path(100.0, 24, np.zeros(10), drift_ea=0.0, sigma_ea=0.1)


def test_unknown_etf_in_a_scenario_raises():
    cfg = synthetic_cfg(scenarios={"bad": {"spy": {"drift_ea": 0.0}}})
    with pytest.raises(ValueError, match="spy"):
        synthetic_panels(make_panel(cfg), cfg)


def test_same_seed_gives_the_same_panels_and_each_etf_its_own_noise():
    cfg = synthetic_cfg(scenarios={"flat": {"icolcap": {"drift_ea": 0.0}, "cspx": {"drift_ea": 0.0}}})
    panel = make_panel(cfg)
    first, second = synthetic_panels(panel, cfg)["flat"], synthetic_panels(panel, cfg)["flat"]
    pd.testing.assert_frame_equal(first, second)
    months = [T0 + m for m in range(25)]
    assert first.loc[months, "icolcap_price_cop"].tolist() != first.loc[months, "cspx_price_cop"].tolist()


def test_scenarios_share_the_noise_draws():
    """Scenarios differ only by their deterministic part: log prices differ by drift * t."""
    cfg = synthetic_cfg()
    panels = synthetic_panels(make_panel(cfg), cfg)
    months = [T0 + m for m in range(25)]
    down = np.log(panels["both_down"].loc[months, "icolcap_price_cop"].to_numpy())
    up = np.log(panels["diverge"].loc[months, "icolcap_price_cop"].to_numpy())
    assert up - down == pytest.approx(0.30 * np.arange(25) / 12)


def test_only_etf_price_and_trend_columns_change_after_t0():
    cfg = synthetic_cfg()
    panel = make_panel(cfg)
    new = synthetic_panels(panel, cfg)["both_down"]
    changed = [c for c in panel.columns if not new[c].equals(panel[c])]
    assert sorted(changed) == sorted(
        ["icolcap_price_cop", "cspx_price_cop", "icolcap_trend_ret", "cspx_trend_ret"]
    )
    pd.testing.assert_frame_equal(new.loc[: T0 - 1], panel.loc[: T0 - 1])


def test_sigma_can_be_overridden_per_etf():
    cfg = synthetic_cfg(
        sigma_ea=0.0,
        scenarios={"s": {"icolcap": {"drift_ea": 0.0}, "cspx": {"drift_ea": 0.0, "sigma_ea": 0.3}}},
    )
    new = synthetic_panels(make_panel(cfg), cfg)["s"]
    months = [T0 + m for m in range(25)]
    assert new.loc[months, "icolcap_price_cop"].tolist() == pytest.approx([100.0] * 25)
    assert new.loc[months, "cspx_price_cop"].std() > 0


def test_trend_filter_leaves_the_etfs_when_both_fall():
    """With sigma 0 both ETFs fall every month after t0 (the history before is flat), so the 12-month
    return is negative at every review after t0: plan 4 holds no ETF there, plan 3 still does."""
    cfg = synthetic_cfg(sigma_ea=0.0)
    panel = synthetic_panels(make_panel(cfg), cfg)["both_down"]
    payments = make_schedule({m: 10.0 for m in range(13, 25)}, horizon=24)
    plan3 = run_backtest(panel, payments, cfg, "ldi").set_index("month")
    plan4 = run_backtest(panel, payments, cfg, "trend_ldi").set_index("month")
    assert plan4.loc[0, "etf_cop"] > 0  # at t0 the trailing return is 0: not below the minimum
    for review in (6, 12, 18):
        assert plan4.loc[review, "etf_cop"] == 0
        assert plan3.loc[review, "etf_cop"] > 0


def test_summary_has_one_row_per_scenario_and_plan():
    cfg = synthetic_cfg()
    panels = synthetic_panels(make_panel(cfg), cfg)
    payments = make_schedule({m: 10.0 for m in range(7, 25)}, horizon=24)
    table = synthetic_summary(panels, payments, cfg)
    assert list(table.columns) == ["scenario", "plan", *METRICS]
    assert len(table) == len(panels) * len(PLANS)


def test_with_prices_updates_the_trailing_return_with_the_new_prices():
    """The trend after the change must be the 12-month return of the new price path, history included."""
    cfg = synthetic_cfg()
    panel = make_panel(cfg)
    rng = np.random.default_rng(0)
    panel["icolcap_price_cop"] = 100 * np.cumprod(1 + rng.normal(0.01, 0.04, len(panel)))
    panel["icolcap_trend_ret"] = panel["icolcap_price_cop"].pct_change(12)
    months = [T0 + m for m in range(25)]
    new_price = panel.loc[months, "icolcap_price_cop"].to_numpy() * np.linspace(1.0, 0.5, 25)
    new = with_prices(panel, cfg, {"icolcap": new_price})
    expected = new["icolcap_price_cop"].pct_change(12)
    assert new.loc[months, "icolcap_trend_ret"].tolist() == pytest.approx(expected[months].tolist())


def test_with_prices_leaves_other_etfs_alone():
    cfg = synthetic_cfg()
    panel = make_panel(cfg)
    new = with_prices(panel, cfg, {"cspx": np.full(25, 50.0)})
    pd.testing.assert_series_equal(new["icolcap_price_cop"], panel["icolcap_price_cop"])
    pd.testing.assert_series_equal(new["icolcap_trend_ret"], panel["icolcap_trend_ret"])

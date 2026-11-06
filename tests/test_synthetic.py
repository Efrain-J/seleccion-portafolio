import numpy as np
import pandas as pd
import pytest
from helpers import make_cfg, make_panel, make_schedule

from uvr_loan.backtest import run_backtest
from uvr_loan.synthetic import (
    METRICS,
    distribution_summary,
    draw_noise,
    median_growth,
    monte_carlo,
    synthetic_panels,
    synthetic_path,
    with_prices,
)

T0 = pd.Period("2020-01", "M")
ZERO = np.zeros(24)


def synthetic_cfg(horizon=24, sigma_ea=0.15, scenarios=None, n_paths=3):
    cfg = make_cfg(horizon=horizon)
    cfg["data"]["vol_window_months"] = 36
    cfg["synthetic_etfs"] = {
        "seed": 1,
        "n_paths": n_paths,
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


def test_only_etf_price_and_volatility_columns_change_after_t0():
    cfg = synthetic_cfg()
    panel = make_panel(cfg)
    new = synthetic_panels(panel, cfg)["both_down"]
    changed = [c for c in panel.columns if not new[c].equals(panel[c])]
    assert sorted(changed) == sorted(
        [f"{name}_{column}" for name in ("icolcap", "cspx") for column in ("price_cop", "vol_ea")]
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


def test_ratchet_holds_less_etf_than_plan_3_when_both_fall():
    """With sigma 0 both ETFs fall every month: the surplus falls from its peak at t0, so at every
    later review plan 4 has cut its ETFs further than plan 3 (as a share of its wealth)."""
    cfg = synthetic_cfg(sigma_ea=0.0)
    panel = synthetic_panels(make_panel(cfg), cfg)["both_down"]
    payments = make_schedule({m: 10.0 for m in range(13, 25)}, horizon=24)
    plan3 = run_backtest(panel, payments, cfg, "ldi").set_index("month")
    plan4 = run_backtest(panel, payments, cfg, "ratchet_ldi").set_index("month")
    for review in (6, 12, 18):
        share3 = plan3.loc[review, "etf_cop"] / plan3.loc[review, "wealth_cop"]
        share4 = plan4.loc[review, "etf_cop"] / plan4.loc[review, "wealth_cop"]
        assert share4 < share3


def test_with_prices_leaves_other_etfs_alone():
    cfg = synthetic_cfg()
    panel = make_panel(cfg)
    new = with_prices(panel, cfg, {"cspx": np.full(25, 50.0)})
    pd.testing.assert_series_equal(new["icolcap_price_cop"], panel["icolcap_price_cop"])
    pd.testing.assert_series_equal(new["icolcap_vol_ea"], panel["icolcap_vol_ea"])


# Volatility follows the new prices (pooled with the historical one while the window is short).


def test_volatility_at_t0_is_the_historical_one():
    cfg = synthetic_cfg()
    panel = make_panel(cfg, icolcap_vol=0.30)
    new = with_prices(panel, cfg, {"icolcap": 100 * np.exp(np.cumsum(np.r_[0, np.ones(24)]) * 0.01)})
    assert new.loc[T0, "icolcap_vol_ea"] == 0.30


def test_volatility_pools_the_historical_one_with_the_new_returns():
    """Constant monthly returns have no variance: after 12 months, 24 of the 36 months still carry
    the historical volatility, so sigma = sigma_0 * sqrt(24 / 36)."""
    cfg = synthetic_cfg()
    panel = make_panel(cfg, icolcap_vol=0.30)
    constant_growth = 100 * 1.01 ** np.arange(25)
    new = with_prices(panel, cfg, {"icolcap": constant_growth})
    assert new.loc[T0 + 12, "icolcap_vol_ea"] == pytest.approx(0.30 * np.sqrt(24 / 36))


def test_volatility_after_a_full_window_is_the_sample_volatility_of_the_new_returns():
    cfg = synthetic_cfg(horizon=48)
    panel = make_panel(cfg, icolcap_vol=0.30)
    returns = np.random.default_rng(3).normal(0.0, 0.05, 48)
    price = 100 * np.cumprod(np.r_[1.0, 1 + returns])
    new = with_prices(panel, cfg, {"icolcap": price})
    expected = np.std(returns[48 - 36 :], ddof=1) * np.sqrt(12)
    assert new.loc[T0 + 48, "icolcap_vol_ea"] == pytest.approx(expected)


# Many paths: one seed, path j uses the same draws in every scenario.


def test_draw_noise_has_one_draw_per_path_etf_and_month_and_is_reproducible():
    cfg = synthetic_cfg(n_paths=4)
    noise = draw_noise(cfg)
    assert noise.shape == (4, 2, 24)
    np.testing.assert_array_equal(noise, draw_noise(cfg))
    assert not np.allclose(noise[0], noise[1])


def test_each_path_has_its_own_prices():
    cfg = synthetic_cfg()
    panel = make_panel(cfg)
    months = [T0 + m for m in range(25)]
    first = synthetic_panels(panel, cfg, path=0)["both_down"].loc[months, "icolcap_price_cop"]
    second = synthetic_panels(panel, cfg, path=1)["both_down"].loc[months, "icolcap_price_cop"]
    assert first.tolist() != pytest.approx(second.tolist())
    noise = draw_noise(cfg)
    again = synthetic_panels(panel, cfg, path=1, noise=noise)["both_down"].loc[months, "icolcap_price_cop"]
    pd.testing.assert_series_equal(second, again)


def test_median_growth_is_the_noise_free_growth_averaged_over_the_etfs():
    cfg = synthetic_cfg()
    growth = median_growth(cfg)
    assert growth["both_down"] == pytest.approx(np.exp(-0.15 * 2) - 1)
    assert growth["diverge"] == pytest.approx((np.exp(0.15 * 2) + np.exp(-0.15 * 2)) / 2 - 1)


def run_small_monte_carlo(workers):
    cfg = synthetic_cfg(n_paths=3)
    payments = make_schedule({m: 10.0 for m in range(7, 25)}, horizon=24)
    return monte_carlo(make_panel(cfg), payments, cfg, workers=workers)


def test_monte_carlo_has_one_row_per_scenario_path_and_plan_and_a_fan():
    paths, fan = run_small_monte_carlo(workers=1)
    assert list(paths.columns) == ["scenario", "path", "plan", *METRICS]
    assert len(paths) == 2 * 3 * 2  # scenarios x paths x plans (3 and 4)
    assert list(fan.columns) == ["scenario", "plan", "month", "p10", "p50", "p90"]
    assert len(fan) == 2 * 2 * 25
    assert (fan["p10"] <= fan["p50"]).all() and (fan["p50"] <= fan["p90"]).all()


def test_monte_carlo_gives_the_same_results_in_parallel():
    serial_paths, serial_fan = run_small_monte_carlo(workers=1)
    parallel_paths, parallel_fan = run_small_monte_carlo(workers=2)
    pd.testing.assert_frame_equal(serial_paths, parallel_paths)
    pd.testing.assert_frame_equal(serial_fan, parallel_fan)


def test_distribution_summary_of_a_hand_made_table():
    paths = pd.DataFrame(
        {
            "scenario": ["s"] * 6,
            "path": [0, 0, 1, 1, 2, 2],
            "plan": ["ldi", "ratchet_ldi"] * 3,
            "final_wealth_net_cop": [100.0, 90.0, 200.0, 210.0, 300.0, 250.0],
            "max_drawdown": [0.1, 0.05, 0.2, 0.1, 0.3, 0.2],
            "shortfall_months": [0, 0, 1, 0, 0, 0],
        }
    )
    plan2 = {"final_wealth_net_cop": 150.0, "max_drawdown": 0.0, "shortfall_months": 2}
    table = distribution_summary(paths, plan2, {"s": 0.5}).set_index("plan")
    assert table.loc["ldi", "wealth_mean"] == pytest.approx(200.0)
    assert table.loc["ldi", "wealth_p50"] == pytest.approx(200.0)
    assert table.loc["ldi", "shortfall_share"] == pytest.approx(1 / 3)
    assert np.isnan(table.loc["ldi", "beats_plan3"])
    assert table.loc["ratchet_ldi", "beats_plan3"] == pytest.approx(1 / 3)  # only path 1
    assert table.loc["cdt_ladder", "wealth_p10"] == table.loc["cdt_ladder", "wealth_p90"] == 150.0
    assert table.loc["cdt_ladder", "beats_plan3"] == pytest.approx(1 / 3)  # 150 > 100 only
    assert table.loc["cdt_ladder", "shortfall_share"] == 1.0
    assert (table["etf_median_growth"] == 0.5).all()

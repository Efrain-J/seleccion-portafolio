import numpy as np
import pandas as pd
import pytest
from helpers import make_cfg, make_panel, make_schedule

from uvr_loan.backtest import run_backtest, summary
from uvr_loan.stress import METRICS, PLANS, crash, drift_down, stress_summary, with_prices

T0 = pd.Period("2020-01", "M")


def varied_prices(cfg):
    panel = make_panel(cfg)
    rng = np.random.default_rng(0)
    for name in ["icolcap", "cspx"]:
        panel[f"{name}_price_cop"] = 100 * np.cumprod(1 + rng.normal(0.01, 0.04, len(panel)))
        panel[f"{name}_trend_ret"] = panel[f"{name}_price_cop"].pct_change(12)
    return panel


def test_drift_down_ends_at_the_ratio_and_keeps_the_history():
    cfg = make_cfg()
    panel = varied_prices(cfg)
    stressed = drift_down(panel, cfg, 0.2)
    for name in ["icolcap", "cspx"]:
        column = f"{name}_price_cop"
        assert stressed.loc[T0 + 12, column] == pytest.approx(0.2 * panel.loc[T0, column])
        pd.testing.assert_series_equal(stressed.loc[: T0, column], panel.loc[: T0, column])


def test_with_prices_updates_the_trailing_return_with_the_new_prices():
    """The trend after the change must be the 12-month return of the new price path, history included."""
    cfg = make_cfg()
    panel = varied_prices(cfg)
    stressed = crash(panel, cfg, at_month=4, fall=0.5)
    expected = stressed["icolcap_price_cop"].pct_change(12)
    months = [T0 + m for m in range(13)]
    assert stressed.loc[months, "icolcap_trend_ret"].tolist() == pytest.approx(expected[months].tolist())
    assert stressed.loc[T0 + 4, "icolcap_trend_ret"] < panel.loc[T0 + 4, "icolcap_trend_ret"]


def test_with_prices_leaves_other_columns_alone():
    cfg = make_cfg()
    panel = varied_prices(cfg)
    stressed = with_prices(panel, cfg, {"cspx": np.full(13, 50.0)})
    pd.testing.assert_series_equal(stressed["icolcap_price_cop"], panel["icolcap_price_cop"])
    pd.testing.assert_series_equal(stressed["uvr_cop"], panel["uvr_cop"])


@pytest.mark.parametrize("plan", ["ldi", "trend_ldi"])
def test_the_floor_plans_pay_everything_when_the_etfs_lose_80_percent(plan):
    cfg = make_cfg()
    payments = {m: 60.0 for m in range(7, 13)}
    results = run_backtest(drift_down(varied_prices(cfg), cfg, 0.2), make_schedule(payments), cfg, plan)
    assert results["shortfall_cop"].sum() == 0


def test_stress_summary_has_one_row_per_scenario_and_plan():
    """The crash scenario falls in month 37, so the horizon must reach it."""
    cfg = make_cfg(horizon=48)
    panel, payments = varied_prices(cfg), make_schedule({m: 10.0 for m in range(7, 49)}, horizon=48)
    table = stress_summary(panel, payments, cfg).set_index(["scenario", "plan"])
    assert list(table.columns) == METRICS
    assert len(table) == 4 * len(PLANS)
    real = summary(run_backtest(panel, payments, cfg, "ldi"))
    assert table.loc[("real", "ldi"), "final_wealth_net_cop"] == pytest.approx(real["final_wealth_net_cop"])
    ladder = table.xs("cdt_ladder", level="plan")["final_wealth_net_cop"]
    assert ladder.tolist() == pytest.approx([ladder.iloc[0]] * 4)  # plan 2 holds no ETF

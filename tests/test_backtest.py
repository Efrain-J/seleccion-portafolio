import pandas as pd
import pytest

from uvr_loan.backtest import run_backtest, summary


def make_cfg(equity_weight=0.10, horizon=12, k=6):
    return {
        "initial_capital_cop": 1_000.0,
        "backtest": {"t0": "2020-01", "horizon_months": horizon, "rebalance_every": k},
        "conservative": {"equity_weight": equity_weight, "liquidity_scenario": "base"},
        "inflation_scenarios": {"base_annual": 0.0, "high_shock_pp": 0.0, "low_shock_pp": 0.0},
    }


def make_panel(cfg, uvr=1.0, fic=0.0, cdt_180=0.0, etf=100.0):
    """Monthly panel from t0 to the end of the horizon; scalars or lists of horizon + 1 values."""
    bt = cfg["backtest"]
    months = pd.period_range(bt["t0"], periods=bt["horizon_months"] + 1, freq="M")
    return pd.DataFrame({"uvr": uvr, "cdt_180": cdt_180, "fic": fic, "etf": etf}, index=months)


def make_schedule(payments, horizon=12):
    months = range(1, horizon + 1)
    return pd.DataFrame({"month": months, "total_payment_uvr": [payments.get(m, 0.0) for m in months]})


def test_no_payments_and_zero_rates_keep_wealth():
    cfg = make_cfg()
    results = run_backtest(make_panel(cfg), make_schedule({}), cfg)
    assert len(results) == 13
    assert results["wealth"].tolist() == pytest.approx([1_000.0] * 13)
    assert results.loc[results["review"], "month"].tolist() == [0, 6]


def test_wealth_grows_at_the_rates():
    cfg = make_cfg(equity_weight=0.0)
    results = run_backtest(make_panel(cfg, fic=0.12, cdt_180=0.12), make_schedule({}), cfg)
    assert results["wealth"].iloc[-1] == pytest.approx(1_000.0 * 1.12)


def test_covered_payments_leave_the_portfolio():
    cfg = make_cfg()
    results = run_backtest(make_panel(cfg), make_schedule({7: 100.0, 8: 100.0}), cfg)
    assert results["shortfall"].sum() == 0
    assert results["wealth"].iloc[-1] == pytest.approx(800.0)
    assert results.set_index("month").loc[6, "fic"] == pytest.approx(200.0)


def test_shortfall_is_recorded_when_uvr_rises_more_than_projected():
    cfg = make_cfg()
    uvr = [1.0] * 7 + [2.0] * 6  # projected flat at the review of month 6, doubles in month 7
    results = run_backtest(make_panel(cfg, uvr=uvr), make_schedule({7: 100.0}), cfg).set_index("month")
    assert results.loc[7, "payment_cop"] == pytest.approx(200.0)
    assert results.loc[7, "shortfall"] == pytest.approx(100.0)
    assert results.loc[7, "fic"] == 0


def test_etf_follows_its_price():
    cfg = make_cfg(equity_weight=1.0)
    etf = [100.0] + [200.0] * 12
    results = run_backtest(make_panel(cfg, etf=etf), make_schedule({}), cfg)
    assert results["etf"].iloc[1] == pytest.approx(2_000.0)


def test_columns_add_up_to_wealth():
    cfg = make_cfg()
    results = run_backtest(make_panel(cfg, fic=0.05, cdt_180=0.08), make_schedule({7: 50.0, 9: 70.0}), cfg)
    assert (results["fic"] + results["cdt"] + results["etf"]).tolist() == pytest.approx(
        results["wealth"].tolist()
    )


def test_summary_of_growing_portfolio():
    cfg = make_cfg(equity_weight=0.0)
    results = run_backtest(make_panel(cfg, fic=0.12, cdt_180=0.12), make_schedule({}), cfg)
    s = summary(results)
    assert s["annual_return"] == pytest.approx(0.12)
    assert s["max_drawdown"] == pytest.approx(0.0)
    assert s["shortfall_months"] == 0
    assert s["final_wealth_cop"] == pytest.approx(1_120.0)


def test_summary_counts_shortfalls_and_payments_are_not_losses():
    cfg = make_cfg()
    uvr = [1.0] * 7 + [2.0] * 6
    results = run_backtest(make_panel(cfg, uvr=uvr), make_schedule({7: 100.0}), cfg)
    s = summary(results)
    assert s["shortfall_months"] == 1
    assert s["total_shortfall_cop"] == pytest.approx(100.0)
    assert s["max_drawdown"] == pytest.approx(0.0)

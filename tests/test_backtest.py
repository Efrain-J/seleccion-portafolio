import pandas as pd
import pytest

from uvr_loan import backtest
from uvr_loan.backtest import STRATEGIES, run_backtest, summary


def make_cfg(equity_weight=0.10, horizon=12, k=6, terms=None):
    return {
        "initial_capital_cop": 1_000.0,
        "backtest": {"t0": "2020-01", "horizon_months": horizon, "rebalance_every": k},
        "conservative": {"equity_weight": equity_weight, "liquidity_scenario": "base"},
        "inflation_scenarios": {"base_lookback_months": 6, "high_shock_pp": 0.0, "low_shock_pp": 0.0},
        "cdt_ladder": {"liquidity_scenario": "base", "terms": terms or {6: "cdt_180"}},
    }


HISTORY = 12  # months of data before t0, as the real panel has (it starts in 2015)


def make_panel(cfg, uvr=1.0, fic=0.0, cdt_180=0.0, etf=100.0, cdt_90=0.0, cdt_360=0.0):
    """Monthly panel from t0 - HISTORY to the end of the horizon.

    Each column is a scalar or a list of horizon + 1 values (months 0..horizon); the history
    before t0 repeats the value of month 0.
    """
    bt = cfg["backtest"]
    start = pd.Period(bt["t0"], "M") - HISTORY
    months = pd.period_range(start, periods=HISTORY + bt["horizon_months"] + 1, freq="M")
    columns = {"uvr": uvr, "cdt_180": cdt_180, "fic": fic, "etf": etf, "cdt_90": cdt_90, "cdt_360": cdt_360}
    padded = {name: [v[0]] * HISTORY + list(v) if isinstance(v, list) else v for name, v in columns.items()}
    return pd.DataFrame(padded, index=months)


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


# Plan 2 (CDT ladder): fixed-rate CDT lots chosen with the LP.


def run_ladder(cfg, payments=None, **panel):
    results = run_backtest(make_panel(cfg, **panel), make_schedule(payments or {}), cfg, "cdt_ladder")
    return results.set_index("month")


def test_ladder_cdt_earns_its_nominal_rate_even_if_the_uvr_doubles():
    """Real money: a fixed-rate CDT pays its observed nominal rate, it is not indexed to the UVR."""
    cfg = make_cfg()
    results = run_ladder(cfg, cdt_180=0.10, uvr=[1.0] * 3 + [2.0] * 10)
    assert results.loc[3, "cdt"] == pytest.approx(1_000.0 * 1.10 ** (3 / 12))


def test_cdt_maturing_at_a_review_is_reinvested_at_that_review():
    cfg = make_cfg()
    results = run_ladder(cfg, cdt_180=0.05)
    assert results.loc[6, "fic"] == pytest.approx(0.0)
    assert results.loc[6, "cdt"] == pytest.approx(results.loc[6, "wealth"])


def test_cdt_maturing_in_the_month_of_a_payment_covers_it():
    """S12: in month 6 the CDT matures first and then the payment is made, with an empty FIC."""
    cfg = make_cfg()
    results = run_ladder(cfg, {6: 100.0}, cdt_180=0.05)
    assert results.loc[5, "fic"] == pytest.approx(0.0)
    assert results["shortfall"].sum() == 0


def test_money_maturing_between_reviews_waits_in_the_fic():
    """S13: a 3-month CDT matures in month 3 and the money earns the FIC rate until the review of month 6."""
    cfg = make_cfg(terms={3: "cdt_90"})
    results = run_ladder(cfg, cdt_90=0.05, fic=0.04)  # FIC below the CDT, so the LP buys the CDT
    matured = 1_000.0 * 1.05 ** (3 / 12)
    assert results.loc[3, "cdt"] == 0
    assert results.loc[3, "fic"] == pytest.approx(matured)
    assert results.loc[5, "fic"] == pytest.approx(matured * 1.04 ** (2 / 12))


def test_live_cdt_enters_the_lp_as_a_known_maturity(monkeypatch):
    """At the review of month 6, the 12-month CDT bought in month 0 is counted as money arriving in month 12."""
    seen = {}
    real_lp = backtest.ladder_purchases

    def spy(tau, budget_uvr, maturities_uvr, *args, **kwargs):
        seen[tau] = dict(maturities_uvr)
        return real_lp(tau, budget_uvr, maturities_uvr, *args, **kwargs)

    monkeypatch.setattr(backtest, "ladder_purchases", spy)
    cfg = make_cfg(terms={12: "cdt_360"})
    run_ladder(cfg, {12: 500.0}, cdt_360=0.10)
    assert seen[0] == {}
    assert seen[6] == {12: pytest.approx(1_100.0)}  # UVR flat and 0 inflation: COP = UVR


def test_ladder_without_a_feasible_plan_keeps_the_money_and_records_the_shortfall():
    """S9: if no ladder covers every payment, nothing is bought and the shortfall is recorded."""
    cfg = make_cfg()
    results = run_ladder(cfg, {7: 5_000.0}, cdt_180=0.05)
    assert results.loc[6, "fic"] == pytest.approx(1_000.0)
    assert results.loc[7, "shortfall"] == pytest.approx(4_000.0)


def test_strategies_only_see_data_up_to_the_review(monkeypatch):
    seen = []

    def spy(tau, history, free, lots, payment_schedule, cfg):
        seen.append((tau, history.index[-1]))
        return free, 0.0, []

    monkeypatch.setitem(STRATEGIES, "spy", spy)
    cfg = make_cfg()
    run_backtest(make_panel(cfg), make_schedule({}), cfg, "spy")
    assert seen == [(0, pd.Period("2020-01", "M")), (6, pd.Period("2020-07", "M"))]

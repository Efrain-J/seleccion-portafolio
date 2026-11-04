import numpy as np
import pandas as pd
import pytest
from helpers import make_cfg, make_panel, make_schedule

from uvr_loan import backtest
from uvr_loan.backtest import PLANS, Allocation, run_backtest, summary


def test_no_payments_and_zero_rates_keep_wealth():
    cfg = make_cfg()
    results = run_backtest(make_panel(cfg), make_schedule({}), cfg)
    assert len(results) == 13
    assert results["wealth_cop"].tolist() == pytest.approx([1_000.0] * 13)
    assert results.loc[results["is_review"], "month"].tolist() == [0, 6]


def test_wealth_grows_at_the_rates():
    cfg = make_cfg(cdt_weight=1.0)
    results = run_backtest(make_panel(cfg, fic=0.12, cdt_180=0.12), make_schedule({}), cfg)
    assert results["wealth_cop"].iloc[-1] == pytest.approx(1_000.0 * 1.12)


def test_covered_payments_leave_the_portfolio():
    cfg = make_cfg()
    results = run_backtest(make_panel(cfg), make_schedule({7: 100.0, 8: 100.0}), cfg)
    assert results["shortfall_cop"].sum() == 0
    assert results["wealth_cop"].iloc[-1] == pytest.approx(800.0)
    assert results.set_index("month").loc[6, "fic_cop"] == pytest.approx(200.0 + 0.10 * 800.0)


def test_conservative_fic_reserves_payments_until_the_month_before_the_cdt_matures():
    """S12 (n - 1): the CDT bought at the review of month 6 matures in month 12 and pays P_12."""
    cfg = make_cfg(cdt_weight=1.0)
    results = run_backtest(make_panel(cfg), make_schedule({m: 10.0 for m in range(7, 13)}), cfg)
    results = results.set_index("month")
    assert results.loc[6, "fic_cop"] == pytest.approx(50.0)  # months 7..11
    assert results["shortfall_cop"].sum() == 0


def test_conservative_puts_everything_in_the_cdt_during_the_grace_period():
    """Reviews before the first payment (tau < grace_months) use grace_cdt_weight = 1: no money waits in the FIC."""
    cfg = make_cfg(grace_months=6)
    results = run_backtest(make_panel(cfg), make_schedule({m: 10.0 for m in range(7, 13)}), cfg).set_index(
        "month"
    )
    assert results.loc[0, "fic_cop"] == pytest.approx(0.0)
    assert results.loc[0, "cdt_cop"] == pytest.approx(1_000.0)
    assert results.loc[6, "fic_cop"] == pytest.approx(
        50.0 + 0.10 * 950.0
    )  # after the grace: L + 10 % of the rest


def test_shortfall_is_recorded_when_uvr_rises_more_than_projected():
    cfg = make_cfg(cdt_weight=1.0)  # the FIC holds only the projected payments
    uvr = [1.0] * 7 + [2.0] * 6  # projected flat at the review of month 6, doubles in month 7
    results = run_backtest(make_panel(cfg, uvr=uvr), make_schedule({7: 100.0}), cfg).set_index("month")
    assert results.loc[7, "payment_cop"] == pytest.approx(200.0)
    assert results.loc[7, "shortfall_cop"] == pytest.approx(100.0)
    assert results.loc[7, "fic_cop"] == 0


def test_conservative_plan_holds_no_etf():
    cfg = make_cfg()
    results = run_backtest(make_panel(cfg, etf=[100.0] + [200.0] * 12), make_schedule({7: 10.0}), cfg)
    assert (results["etf_cop"] == 0).all()


def test_etf_follows_its_price(monkeypatch):
    """The engine still supports an ETF (for future plans): a plan that puts everything in it."""

    def all_in_etf(tau, history, free_cop, lots, payment_schedule, cfg):
        return Allocation(0.0, {"icolcap": free_cop}, [])

    monkeypatch.setitem(PLANS, "all_in_etf", all_in_etf)
    cfg = make_cfg()
    etf = [100.0] + [200.0] * 12
    results = run_backtest(make_panel(cfg, etf=etf), make_schedule({}), cfg, "all_in_etf")
    assert results["etf_cop"].iloc[1] == pytest.approx(2_000.0)


# The ETF is liquidity too: when the FIC cannot cover a payment, ETF units are sold (S9).


def run_split(monkeypatch, fic_share, payments, etf=100.0):
    """A plan that keeps `fic_share` of the free money in the FIC and the rest in the ETF."""

    def split(tau, history, free_cop, lots, payment_schedule, cfg):
        return Allocation(fic_share * free_cop, {"icolcap": (1 - fic_share) * free_cop}, [])

    monkeypatch.setitem(PLANS, "split", split)
    cfg = make_cfg()
    return run_backtest(make_panel(cfg, etf=etf), make_schedule(payments), cfg, "split").set_index("month")


def test_etf_is_sold_when_the_fic_cannot_cover_a_payment(monkeypatch):
    results = run_split(monkeypatch, 0.0, {7: 100.0})  # everything in the ETF, price flat at 100
    assert results.loc[7, "shortfall_cop"] == 0
    assert results.loc[7, "etf_sold_cop"] == pytest.approx(100.0)
    assert results.loc[7, "etf_cop"] == pytest.approx(900.0)


def test_etf_is_sold_at_the_price_of_the_month(monkeypatch):
    etf = [100.0] * 7 + [50.0] * 6  # the price halves in month 7
    results = run_split(monkeypatch, 0.0, {7: 100.0}, etf=etf)
    assert results.loc[7, "etf_sold_cop"] == pytest.approx(100.0)
    assert results.loc[7, "etf_cop"] == pytest.approx(500.0 - 100.0)


def test_fic_pays_first_and_the_etf_only_covers_the_rest(monkeypatch):
    results = run_split(monkeypatch, 0.5, {7: 600.0})  # FIC 500, ETF 500
    assert results.loc[7, "fic_cop"] == 0
    assert results.loc[7, "etf_sold_cop"] == pytest.approx(100.0)
    assert results.loc[7, "shortfall_cop"] == 0


def test_shortfall_remains_when_fic_and_etf_are_not_enough(monkeypatch):
    results = run_split(monkeypatch, 0.5, {7: 1_200.0})
    assert results.loc[7, "etf_sold_cop"] == pytest.approx(500.0)
    assert results.loc[7, "etf_cop"] == pytest.approx(0.0)
    assert results.loc[7, "shortfall_cop"] == pytest.approx(200.0)


def test_nothing_is_sold_when_the_fic_is_enough(monkeypatch):
    results = run_split(monkeypatch, 0.5, {7: 100.0})
    assert (results["etf_sold_cop"] == 0).all()


def test_summary_liquidity_counts_fic_and_etf(monkeypatch):
    results = run_split(monkeypatch, 0.5, {7: 100.0})
    assert summary(results.reset_index())["min_liquid_at_payment_cop"] == pytest.approx(400.0 + 500.0)


def test_columns_add_up_to_wealth():
    cfg = make_cfg()
    results = run_backtest(make_panel(cfg, fic=0.05, cdt_180=0.08), make_schedule({7: 50.0, 9: 70.0}), cfg)
    assert (results["fic_cop"] + results["cdt_cop"] + results["etf_cop"]).tolist() == pytest.approx(
        results["wealth_cop"].tolist()
    )


def test_summary_of_growing_portfolio():
    cfg = make_cfg(cdt_weight=1.0)
    results = run_backtest(make_panel(cfg, fic=0.12, cdt_180=0.12), make_schedule({}), cfg)
    s = summary(results)
    assert s["annual_return"] == pytest.approx(0.12)
    assert s["max_drawdown"] == pytest.approx(0.0)
    assert s["shortfall_months"] == 0
    assert s["final_wealth_cop"] == pytest.approx(1_120.0)


def test_summary_counts_shortfalls_and_payments_are_not_losses():
    cfg = make_cfg(cdt_weight=1.0)
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
    assert results.loc[3, "cdt_cop"] == pytest.approx(1_000.0 * 1.10 ** (3 / 12))


def test_cdt_maturing_at_a_review_is_reinvested_at_that_review():
    cfg = make_cfg()
    results = run_ladder(cfg, cdt_180=0.05)
    assert results.loc[6, "fic_cop"] == pytest.approx(
        0.0, abs=1e-3
    )  # tie-break tolerance can leave a fraction of a peso
    assert results.loc[6, "cdt_cop"] == pytest.approx(results.loc[6, "wealth_cop"], abs=1e-3)


def test_cdt_maturing_in_the_month_of_a_payment_covers_it():
    """S12: in month 6 the CDT matures first and then the payment is made, with an empty FIC."""
    cfg = make_cfg()
    results = run_ladder(cfg, {6: 100.0}, cdt_180=0.05)
    assert results.loc[5, "fic_cop"] == pytest.approx(0.0, abs=1e-3)
    assert results["shortfall_cop"].sum() == 0


def test_money_maturing_between_reviews_waits_in_the_fic():
    """S13: a 3-month CDT matures in month 3 and the money earns the FIC rate until the review of month 6."""
    cfg = make_cfg(terms={3: "cdt_90d_ea"})
    results = run_ladder(cfg, cdt_90=0.05, fic=0.04)  # FIC below the CDT, so the LP buys the CDT
    matured = 1_000.0 * 1.05 ** (3 / 12)
    assert results.loc[3, "cdt_cop"] == 0
    assert results.loc[3, "fic_cop"] == pytest.approx(matured)
    assert results.loc[5, "fic_cop"] == pytest.approx(matured * 1.04 ** (2 / 12))


def test_live_cdt_enters_the_lp_as_a_known_maturity(monkeypatch):
    """At the review of month 6, the 12-month CDT bought in month 0 is counted as money arriving in month 12."""
    seen = {}
    real_lp = backtest.ladder_purchases

    def spy(tau, budget_uvr, maturities_uvr, *args, **kwargs):
        seen[tau] = dict(maturities_uvr)
        return real_lp(tau, budget_uvr, maturities_uvr, *args, **kwargs)

    monkeypatch.setattr(backtest, "ladder_purchases", spy)
    cfg = make_cfg(terms={12: "cdt_360d_ea"})
    run_ladder(cfg, {12: 500.0}, cdt_360=0.10)
    assert seen[0] == {}
    assert seen[6] == {12: pytest.approx(1_100.0)}  # UVR flat and 0 inflation: COP = UVR


def test_ladder_without_a_feasible_plan_keeps_the_money_and_records_the_shortfall():
    """S9: if no ladder covers every payment, nothing is bought and the shortfall is recorded."""
    cfg = make_cfg()
    results = run_ladder(cfg, {7: 5_000.0}, cdt_180=0.05)
    assert results.loc[6, "fic_cop"] == pytest.approx(1_000.0)
    assert results.loc[7, "shortfall_cop"] == pytest.approx(4_000.0)


def test_strategies_only_see_data_up_to_the_review(monkeypatch):
    seen = []

    def spy(tau, history, free, lots, payment_schedule, cfg):
        seen.append((tau, history.index[-1]))
        return Allocation(free, {}, [])

    monkeypatch.setitem(PLANS, "spy", spy)
    cfg = make_cfg()
    run_backtest(make_panel(cfg), make_schedule({}), cfg, "spy")
    assert seen == [(0, pd.Period("2020-01", "M")), (6, pd.Period("2020-07", "M"))]


def test_net_wealth_deducts_the_accumulated_shortfall():
    """An unpaid payment is still owed: the net wealth subtracts every shortfall so far."""
    cfg = make_cfg(cdt_weight=1.0)
    uvr = [1.0] * 7 + [2.0] * 6  # month 7 has a shortfall of 100 COP
    results = run_backtest(make_panel(cfg, uvr=uvr), make_schedule({7: 100.0}), cfg).set_index("month")
    assert results.loc[6, "wealth_net_cop"] == pytest.approx(results.loc[6, "wealth_cop"])
    assert results.loc[7, "wealth_net_cop"] == pytest.approx(results.loc[7, "wealth_cop"] - 100.0)
    assert results.loc[12, "wealth_net_cop"] == pytest.approx(results.loc[12, "wealth_cop"] - 100.0)
    s = summary(results.reset_index())
    assert s["final_wealth_net_cop"] == pytest.approx(s["final_wealth_cop"] - 100.0)


# Plan 3 (LDI): the ladder gets 1.05 x floor and the ETFs the rest, split by inverse volatility.


def run_ldi(cfg, payments, **panel):
    return run_backtest(make_panel(cfg, **panel), make_schedule(payments), cfg, "ldi").set_index("month")


def test_ldi_puts_the_money_above_the_floor_in_the_etfs():
    """Zero rates: the floor is the payment (100), the ladder gets 105 and the ETFs the other 895."""
    results = run_ldi(make_cfg(), {7: 100.0})
    assert results.loc[0, "floor_cop"] == pytest.approx(100.0)
    assert results.loc[0, "funding_ratio_total"] == pytest.approx(10.0)  # no live CDTs yet
    assert results.loc[0, "etf_cop"] == pytest.approx(895.0)
    assert results.loc[0, "icolcap_cop"] == pytest.approx(447.5)  # equal volatilities: half each
    assert results.loc[0, "cdt_cop"] + results.loc[0, "fic_cop"] == pytest.approx(105.0)


def test_ldi_splits_the_etfs_by_inverse_volatility():
    results = run_ldi(make_cfg(), {7: 100.0}, icolcap_vol=0.1, cspx_vol=0.3)
    assert results.loc[0, "icolcap_cop"] == pytest.approx(0.75 * 895.0)
    assert results.loc[0, "cspx_cop"] == pytest.approx(0.25 * 895.0)


def test_ldi_buys_no_etf_when_the_money_is_below_the_buffered_floor():
    cfg = {**make_cfg(), "initial_capital_cop": 102.0}  # floor 100 < 102 < 105
    results = run_ldi(cfg, {7: 100.0})
    assert results.loc[0, "etf_cop"] == 0
    assert results["shortfall_cop"].sum() == 0


def test_ldi_below_the_floor_keeps_the_money_in_the_fic():
    cfg = {**make_cfg(), "initial_capital_cop": 50.0}
    results = run_ldi(cfg, {7: 100.0})
    assert results.loc[0, "fic_cop"] == pytest.approx(50.0)
    assert results.loc[0, "etf_cop"] == 0
    assert results.loc[7, "shortfall_cop"] == pytest.approx(50.0)


def test_a_crash_of_the_etfs_does_not_reach_the_payments():
    """m = 1: the ETFs lose 99 % after month 0, and the ladder still pays everything."""
    crash = [100.0] + [1.0] * 12
    results = run_ldi(make_cfg(), {7: 100.0, 12: 100.0}, etf=crash, cspx=crash)
    assert results["shortfall_cop"].sum() == 0
    assert results["etf_sold_cop"].sum() == 0


def test_etfs_are_sold_pro_rata(monkeypatch):
    def two_etfs(tau, history, free_cop, lots, payment_schedule, cfg):
        return Allocation(0.0, {"icolcap": 0.6 * free_cop, "cspx": 0.4 * free_cop}, [])

    monkeypatch.setitem(PLANS, "two_etfs", two_etfs)
    cfg = make_cfg()
    results = run_backtest(make_panel(cfg), make_schedule({3: 100.0}), cfg, "two_etfs").set_index("month")
    assert results.loc[3, "etf_sold_cop"] == pytest.approx(100.0)
    assert results.loc[3, "icolcap_cop"] == pytest.approx(600.0 - 60.0)
    assert results.loc[3, "cspx_cop"] == pytest.approx(400.0 - 40.0)


def test_plans_without_a_floor_record_no_funding_ratio():
    results = run_backtest(make_panel(make_cfg()), make_schedule({}), make_cfg())
    assert results["floor_cop"].isna().all()
    assert results["funding_ratio_total"].isna().all()


def test_total_funding_ratio_counts_the_live_cdts_on_both_sides():
    """At the review of month 6 the 12-month CDT bought in month 0 covers the payment, so the floor of the
    free money is 0; the total ratio stays finite: (free money + live CDT) / (0 + live CDT)."""
    cfg = make_cfg(terms={12: "cdt_360d_ea"})
    results = run_ldi(cfg, {12: 100.0}, cdt_360=0.10)  # floor in month 0: 100 / 1.10
    live = 1.05 * 100.0 / 1.10 * 1.10 ** (6 / 12)
    assert results.loc[6, "floor_cop"] == 0.0
    assert results.loc[6, "cdt_cop"] == pytest.approx(live)  # nothing new is bought
    assert results.loc[6, "funding_ratio_total"] == pytest.approx(results.loc[6, "wealth_cop"] / live)


def test_total_funding_ratio():
    assert backtest.total_funding_ratio(300.0, 100.0, 100.0) == pytest.approx(2.0)
    assert backtest.total_funding_ratio(300.0, 0.0, 0.0) == float("inf")  # nothing left to pay
    assert np.isnan(backtest.total_funding_ratio(300.0, 100.0, float("nan")))  # plan without a floor


def test_ldi_without_growth_assets_raises_instead_of_losing_the_money():
    cfg = make_cfg()
    cfg["ldi"] = {**cfg["ldi"], "growth_assets": []}
    with pytest.raises(ValueError, match="no growth assets"):
        run_ldi(cfg, {7: 100.0})


def test_ldi_with_a_missing_volatility_raises_instead_of_returning_nan():
    with pytest.raises(ValueError, match="icolcap"):
        run_ldi(make_cfg(), {7: 100.0}, icolcap_vol=float("nan"))


def test_only_the_etfs_of_the_config_are_tracked():
    """An extra `<name>_price_cop` column in the panel is not an ETF unless it is in `data.etfs`."""
    cfg = make_cfg()
    panel = make_panel(cfg)
    panel["tes_price_cop"] = 100.0
    results = run_backtest(panel, make_schedule({}), cfg, "ldi")
    assert "tes_cop" not in results.columns
    assert {"icolcap_cop", "cspx_cop"} <= set(results.columns)

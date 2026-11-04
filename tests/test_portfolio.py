import pandas as pd
import pytest

from uvr_loan.portfolio import conservative_allocation, ladder_purchases

PARAMS = {"equity_weight": 0.10}


LP_CFG = {"backtest": {"horizon_months": 12, "rebalance_every": 6}}


def lp_schedule(payments, horizon=12):
    months = range(1, horizon + 1)
    return pd.DataFrame({"month": months, "total_payment_uvr": [payments.get(m, 0.0) for m in months]})


WINDOW = {m: 10.0 for m in range(7, 13)}  # 10 UVR in each month of the window (6, 12]


def test_no_payments_during_grace():
    alloc = conservative_allocation(760e6, [0.0] * 6, PARAMS)
    assert alloc["fic"] == 0
    assert alloc["etf"] == pytest.approx(76e6)
    assert alloc["cdt"] == pytest.approx(684e6)
    assert alloc["shortfall"] == 0


def test_fic_covers_next_payments():
    alloc = conservative_allocation(500e6, [5e6] * 6, PARAMS)
    assert alloc["fic"] == pytest.approx(30e6)
    assert alloc["etf"] == pytest.approx(0.10 * 470e6)


@pytest.mark.parametrize(
    "wealth,payments",
    [(760e6, [0.0] * 6), (500e6, [5e6] * 6), (100e6, [90e6, 5e6])],
)
def test_allocation_adds_up_and_is_non_negative(wealth, payments):
    alloc = conservative_allocation(wealth, payments, PARAMS)
    assert alloc["fic"] + alloc["cdt"] + alloc["etf"] == pytest.approx(wealth)
    assert min(alloc["fic"], alloc["cdt"], alloc["etf"]) >= 0


def test_shortfall_when_payments_exceed_wealth():
    alloc = conservative_allocation(10e6, [8e6, 8e6], PARAMS)
    assert alloc["fic"] == pytest.approx(10e6)
    assert alloc["cdt"] == 0
    assert alloc["etf"] == 0
    assert alloc["shortfall"] == pytest.approx(6e6)


def test_ladder_budget_equal_to_payment_is_enough_with_zero_spread():
    buy = ladder_purchases(0, 100.0, {}, lp_schedule({12: 100.0}), LP_CFG, {6: 0.0, 12: 0.0})
    assert 0 <= sum(buy.values()) <= 100.0 + 1e-9


def test_ladder_spread_lowers_the_cost():
    buy = ladder_purchases(0, 100.0, {}, lp_schedule({12: 102.0}), LP_CFG, {12: 0.02})
    assert buy[12] == pytest.approx(100.0)


def test_ladder_prefers_the_higher_spread_that_fits():
    buy = ladder_purchases(0, 100.0, {}, lp_schedule({12: 100.0}), LP_CFG, {6: 0.01, 12: 0.02})
    assert buy[6] == pytest.approx(0.0)
    assert buy[12] == pytest.approx(100.0)


def test_ladder_lots_do_not_mature_after_the_horizon():
    buy = ladder_purchases(6, 100.0, {}, lp_schedule({12: 50.0}), LP_CFG, {6: 0.0, 12: 0.05})
    assert buy[12] == 0.0


def test_ladder_raises_when_budget_is_not_enough():
    with pytest.raises(ValueError, match="month 0"):
        ladder_purchases(0, 50.0, {}, lp_schedule({12: 100.0}), LP_CFG, {12: 0.0})


# Liquidity that arrives inside the window (S12: a CDT maturing in month m pays month m).
# Review at tau = 6, next review at 12; the budget B = 60 covers the whole window by itself.


def test_live_cdt_maturing_inside_the_window_frees_cash_to_invest():
    """CDT matures in month 8 (n = 2): cash only for P_7 (n - 1 payments), the rest is invested."""
    buy = ladder_purchases(6, 60.0, {8: 100.0}, lp_schedule(WINDOW), LP_CFG, {6: 0.02})
    assert buy[6] == pytest.approx(50.0)  # cash kept = 10; 60 would ignore the CDT, 20 is off by one


def test_live_cdt_maturing_next_month_needs_no_cash():
    """CDT matures in month 7 (n = 1) and covers every payment of the window."""
    buy = ladder_purchases(6, 60.0, {7: 100.0}, lp_schedule(WINDOW), LP_CFG, {6: 0.02})
    assert buy[6] == pytest.approx(60.0)


def test_live_cdt_maturing_at_the_next_review():
    """CDT matures in month 12 (n = k): cash for P_7 .. P_11, the CDT pays P_12."""
    buy = ladder_purchases(6, 60.0, {12: 10.0}, lp_schedule(WINDOW), LP_CFG, {6: 0.02})
    assert buy[6] == pytest.approx(10.0)


def test_without_a_live_cdt_only_the_new_one_frees_the_last_payment():
    """No live CDT: the new 6-month CDT matures in month 12 and pays P_12, so cash covers P_7 .. P_11."""
    buy = ladder_purchases(6, 60.0, {}, lp_schedule(WINDOW), LP_CFG, {6: 0.02})
    assert buy[6] == pytest.approx(10.0)


def test_cash_losing_real_value_needs_a_bigger_budget():
    """Cash that waits one month earns `cash_rate` in UVR; at -12 % a year, 10 UVR of cash are not enough."""
    payment = lp_schedule({1: 10.0})
    with pytest.raises(ValueError):
        ladder_purchases(0, 10.0, {}, payment, LP_CFG, {6: 0.0}, cash_rate=-0.12)
    ladder_purchases(0, 10.0 / 0.88 ** (1 / 12), {}, payment, LP_CFG, {6: 0.0}, cash_rate=-0.12)

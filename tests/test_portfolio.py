import math

import pandas as pd
import pytest

from uvr_loan.portfolio import (
    conservative_allocation,
    inverse_volatility_weights,
    ladder_floor,
    ladder_purchases,
)

PARAMS = {"cdt_weight": 0.90}


LP_CFG = {"backtest": {"horizon_months": 12, "review_every_months": 6}}


def lp_schedule(payments, horizon=12):
    months = range(1, horizon + 1)
    return pd.DataFrame({"month": months, "total_payment_uvr": [payments.get(m, 0.0) for m in months]})


WINDOW = {m: 10.0 for m in range(7, 13)}  # 10 UVR in each month of the window (6, 12]


def test_no_payments_during_grace():
    """Without payments, the CDT takes cdt_weight of the money and the FIC the rest; there is no ETF."""
    alloc = conservative_allocation(760e6, [0.0] * 6, PARAMS)
    assert alloc["fic_cop"] == pytest.approx(76e6)
    assert alloc["cdt_cop"] == pytest.approx(684e6)
    assert alloc["uncovered_cop"] == 0
    assert "etf_cop" not in alloc


def test_fic_covers_next_payments_and_keeps_the_rest_of_its_share():
    alloc = conservative_allocation(500e6, [5e6] * 6, PARAMS)
    assert alloc["fic_cop"] == pytest.approx(30e6 + 0.10 * 470e6)
    assert alloc["cdt_cop"] == pytest.approx(0.90 * 470e6)


@pytest.mark.parametrize(
    "wealth,payments",
    [(760e6, [0.0] * 6), (500e6, [5e6] * 6), (100e6, [90e6, 5e6])],
)
def test_allocation_adds_up_and_is_non_negative(wealth, payments):
    alloc = conservative_allocation(wealth, payments, PARAMS)
    assert alloc["fic_cop"] + alloc["cdt_cop"] == pytest.approx(wealth)
    assert min(alloc["fic_cop"], alloc["cdt_cop"]) >= 0


def test_shortfall_when_payments_exceed_wealth():
    alloc = conservative_allocation(10e6, [8e6, 8e6], PARAMS)
    assert alloc["fic_cop"] == pytest.approx(10e6)
    assert alloc["cdt_cop"] == 0
    assert alloc["uncovered_cop"] == pytest.approx(6e6)


def test_ladder_budget_equal_to_payment_is_enough_with_zero_real_rate():
    buy = ladder_purchases(0, 100.0, {}, lp_schedule({12: 100.0}), LP_CFG, {6: 0.0, 12: 0.0})
    assert 0 <= sum(buy.values()) <= 100.0 + 1e-9


def test_ladder_higher_real_rate_lowers_the_cost():
    buy = ladder_purchases(0, 100.0, {}, lp_schedule({12: 102.0}), LP_CFG, {12: 0.02})
    assert buy[12] == pytest.approx(100.0)


def test_ladder_prefers_the_higher_real_rate_that_fits():
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
    """Cash that waits one month earns `fic_real_ea` in UVR; at -12 % a year, 10 UVR of cash are not enough."""
    payment = lp_schedule({1: 10.0})
    with pytest.raises(ValueError):
        ladder_purchases(0, 10.0, {}, payment, LP_CFG, {6: 0.0}, fic_real_ea=-0.12)
    ladder_purchases(0, 10.0 / 0.88 ** (1 / 12), {}, payment, LP_CFG, {6: 0.0}, fic_real_ea=-0.12)


# Tie-break and solver status.


def test_ladder_breaks_ties_toward_the_shorter_term():
    """Same real rate for 6 and 12 months: two 6-month CDTs equal one 12-month CDT, so the shorter term is chosen."""
    buy = ladder_purchases(0, 100.0, {}, lp_schedule({}), LP_CFG, {6: 0.02, 12: 0.02})
    assert buy[6] == pytest.approx(100.0)
    assert buy[12] == pytest.approx(0.0)


@pytest.mark.parametrize("method", ["highs-ds", "highs-ipm"])
def test_ladder_purchases_do_not_depend_on_the_solver_method(monkeypatch, method):
    """With the tie-break the purchase is unique: forcing another HiGHS method gives the same result."""
    from scipy.optimize import linprog

    from uvr_loan import portfolio

    def other_method(*args, **kwargs):
        return linprog(*args, **{**kwargs, "method": method})

    reference = ladder_purchases(0, 100.0, {}, lp_schedule({}), LP_CFG, {6: 0.02, 12: 0.02})
    monkeypatch.setattr(portfolio, "linprog", other_method)
    result = ladder_purchases(0, 100.0, {}, lp_schedule({}), LP_CFG, {6: 0.02, 12: 0.02})
    assert result == pytest.approx(reference, abs=1e-6)


def test_ladder_solver_failure_other_than_infeasible_is_not_hidden(monkeypatch):
    """Only an infeasible LP (status 2) means "no ladder"; other solver failures must raise RuntimeError."""
    from types import SimpleNamespace

    from uvr_loan import portfolio

    monkeypatch.setattr(portfolio, "linprog", lambda *a, **k: SimpleNamespace(status=4, message="numerical"))
    with pytest.raises(RuntimeError, match="numerical"):
        ladder_purchases(0, 100.0, {}, lp_schedule({12: 50.0}), LP_CFG, {12: 0.0})


# Plan 3: the floor is the smallest budget of the same LP, and the ETFs are split by inverse volatility.


def test_floor_with_zero_real_rates_is_the_sum_of_the_payments():
    floor = ladder_floor(0, {}, lp_schedule({7: 30.0, 12: 70.0}), LP_CFG, {6: 0.0, 12: 0.0})
    assert floor == pytest.approx(100.0)


def test_floor_discounts_the_payments_at_the_real_rate():
    floor = ladder_floor(0, {}, lp_schedule({12: 102.0}), LP_CFG, {12: 0.02})
    assert floor == pytest.approx(100.0)


def test_the_floor_is_the_smallest_budget_the_ladder_accepts():
    args = ({}, lp_schedule({7: 30.0, 12: 70.0}), LP_CFG, {6: 0.01, 12: 0.03})
    floor = ladder_floor(0, *args, fic_real_ea=-0.02)
    ladder_purchases(0, floor * (1 + 1e-9), *args, fic_real_ea=-0.02)
    with pytest.raises(ValueError):
        ladder_purchases(0, floor * 0.999, *args, fic_real_ea=-0.02)


def test_live_cdts_lower_the_floor_and_it_is_never_negative():
    payments = lp_schedule({12: 100.0})
    assert ladder_floor(0, {12: 40.0}, payments, LP_CFG, {12: 0.0}) == pytest.approx(60.0)
    covered = ladder_floor(0, {12: 500.0}, payments, LP_CFG, {12: 0.0})
    assert covered == 0.0
    assert not math.copysign(1.0, covered) < 0  # not -0.0


def test_inverse_volatility_weights():
    assert inverse_volatility_weights({"a": 0.2, "b": 0.2}) == pytest.approx({"a": 0.5, "b": 0.5})
    assert inverse_volatility_weights({"a": 0.1, "b": 0.3}) == pytest.approx({"a": 0.75, "b": 0.25})

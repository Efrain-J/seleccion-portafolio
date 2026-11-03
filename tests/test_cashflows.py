import pandas as pd
import pytest

from uvr_loan.cashflows import decision_months, month_to_period, projected_payments_cop
from uvr_loan.inflation import project_uvr


def test_decision_months_from_config(cfg):
    assert decision_months(cfg["backtest"]) == list(range(0, 120, 6))


@pytest.mark.parametrize("k", [3, 6, 12])
def test_decision_months_sensitivity(cfg, k):
    assert k in cfg["backtest"]["rebalance_sensitivity"]
    months = decision_months({**cfg["backtest"], "rebalance_every": k})
    assert months[0] == 0
    assert months[-1] == 120 - k
    assert len(months) == 120 // k


def test_month_to_period(cfg):
    t0 = cfg["backtest"]["t0"]
    assert month_to_period(t0, 0) == pd.Period("2016-10", "M")
    assert month_to_period(t0, 1) == pd.Period("2016-11", "M")
    assert month_to_period(t0, 37) == pd.Period("2019-11", "M")
    assert month_to_period(t0, 120) == pd.Period("2026-10", "M")


def test_no_payments_during_grace(payment_schedule):
    payments = projected_payments_cop(payment_schedule, 0, 243.0, 0.06, 6)
    assert list(payments.index) == [1, 2, 3, 4, 5, 6]
    assert (payments == 0).all()


def test_first_payment_after_grace(payment_schedule):
    uvr_tau, inflation = 270.0, 0.06
    payments = projected_payments_cop(payment_schedule, 36, uvr_tau, inflation, 6)
    c = payment_schedule.set_index("month").loc[37, "installment_uvr"]
    assert payments[37] == pytest.approx(c * project_uvr(uvr_tau, inflation, 1)[0])


def test_window_with_prepayment(payment_schedule):
    payments = projected_payments_cop(payment_schedule, 42, 1.0, 0.0, 6)
    expected = payment_schedule.set_index("month").loc[48, "total_payment_uvr"]
    assert payments[48] == pytest.approx(expected)


def test_window_is_cut_at_maturity(payment_schedule):
    payments = projected_payments_cop(payment_schedule, 117, 1.0, 0.0, 6)
    assert list(payments.index) == [118, 119, 120]

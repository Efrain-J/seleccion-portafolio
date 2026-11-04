import pytest

from uvr_loan.amortization import installment, monthly_rate, schedule


def test_monthly_rate():
    assert monthly_rate(0.10) == pytest.approx(0.0079741404, abs=1e-10)


def test_installment(loan_cfg):
    c = installment(
        loan_cfg["principal_uvr"],
        loan_cfg["annual_rate"],
        loan_cfg["term_months"],
        loan_cfg["grace_months"],
        loan_cfg["prepayments_uvr"],
    )
    assert c == pytest.approx(20_379.5327, abs=1e-4)


def test_balance_after_grace_and_at_maturity(payment_schedule):
    balance = payment_schedule.set_index("month")["closing_balance_uvr"]
    assert balance[36] == pytest.approx(1_331_000)
    assert balance[120] == pytest.approx(0, abs=1e-6)


def test_payments(payment_schedule):
    total = payment_schedule.set_index("month")["total_payment_uvr"]
    assert len(total) == 120
    assert (total.loc[1:36] == 0).all()
    assert total[48] == pytest.approx(70_379.5327, abs=1e-4)
    assert total[60] == pytest.approx(70_379.5327, abs=1e-4)


@pytest.mark.parametrize("rate,term,grace", [(0.10, 120, 36), (0.05, 60, 0), (0.12, 24, 12)])
def test_installment_without_prepayments_is_plain_annuity(rate, term, grace):
    i = monthly_rate(rate)
    n = term - grace
    expected = 1_000 * (1 + i) ** grace * i / (1 - (1 + i) ** -n)
    assert installment(1_000, rate, term, grace, {}) == pytest.approx(expected)


def test_schedule_without_prepayments_ends_at_zero(loan_cfg):
    table = schedule({**loan_cfg, "prepayments_uvr": {}})
    assert table["closing_balance_uvr"].iloc[-1] == pytest.approx(0, abs=1e-6)


@pytest.mark.parametrize(
    "change,message",
    [
        ({"grace_months": 120}, "grace"),
        ({"grace_months": -1}, "grace"),
        ({"prepayments_uvr": {130: 50_000}}, "130"),
        ({"prepayments_uvr": {48: 2_000_000}}, "negative"),
    ],
    ids=[
        "grace-equal-to-term",
        "negative-grace",
        "prepayment-after-the-term",
        "prepayment-above-the-balance",
    ],
)
def test_schedule_rejects_invalid_loans(loan_cfg, change, message):
    """Before, these loans gave a wrong schedule (balance not 0, negative balance) or a ZeroDivisionError."""
    with pytest.raises(ValueError, match=message):
        schedule({**loan_cfg, **change})


def test_installment_rejects_a_grace_period_as_long_as_the_term():
    with pytest.raises(ValueError, match="grace"):
        installment(1_000, 0.10, 12, 12, {})

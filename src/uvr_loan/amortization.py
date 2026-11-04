"""UVR amortization schedule: full grace period plus scheduled prepayments.

Ports the logic of P1_cuotas.ipynb. Run `python -m uvr_loan.amortization`
to write data/processed/payment_schedule_uvr.csv.
"""

from typing import Any

import numpy as np
import pandas as pd

from uvr_loan.config import ROOT, load_assumptions

OUTPUT_PATH = ROOT / "data" / "processed" / "payment_schedule_uvr.csv"
NEGATIVE_BALANCE_TOLERANCE_UVR = 1e-6  # rounding of the last installment, not a real negative balance


def monthly_rate(annual_rate: float) -> float:
    return (1 + annual_rate) ** (1 / 12) - 1


def _check_loan(term: int, grace: int, prepayments: dict[int, float]) -> None:
    """Raise ValueError if the grace period or a prepayment month does not fit in the term."""
    if not 0 <= grace < term:
        raise ValueError(f"The grace period must satisfy 0 <= grace < term, got grace={grace}, term={term}")
    outside = [m for m in prepayments if not 1 <= m <= term]
    if outside:
        raise ValueError(f"Prepayments must fall in months 1..{term}, got months {outside}")


def installment(
    principal: float,
    annual_rate: float,
    term: int,
    grace: int,
    prepayments: dict[int, float],
) -> float:
    """Fixed monthly installment (UVR) paid after the grace period.

    Balance capitalized at the end of the grace period, minus the present value
    of the prepayments, spread as an annuity over the remaining months.
    """
    _check_loan(term, grace, prepayments)
    i = monthly_rate(annual_rate)
    n = term - grace
    balance_grace = principal * (1 + i) ** grace
    pv_prepayments = sum(v / (1 + i) ** (m - grace) for m, v in prepayments.items())
    return (balance_grace - pv_prepayments) * i / (1 - (1 + i) ** -n)


def schedule(loan: dict[str, Any]) -> pd.DataFrame:
    """Month-by-month table (months 1..term) from the `loan` section of the config.

    Raises ValueError for a loan that does not fit in its term or whose balance becomes negative
    (a prepayment larger than the balance).
    """
    principal = loan["principal_uvr"]
    rate = loan["annual_rate"]
    term = loan["term_months"]
    grace = loan["grace_months"]
    prepayments = {int(m): v for m, v in loan["prepayments_uvr"].items()}

    i = monthly_rate(rate)
    c = installment(principal, rate, term, grace, prepayments)

    months = np.arange(1, term + 1)
    installments = np.where(months > grace, c, 0.0)
    prepays = np.array([prepayments.get(m, 0.0) for m in months], dtype=float)

    opening, interest, closing = (np.zeros(term) for _ in range(3))
    balance = principal
    for t in range(term):
        opening[t] = balance
        interest[t] = balance * i
        balance = balance + interest[t] - installments[t] - prepays[t]
        closing[t] = balance

    if closing.min() < -NEGATIVE_BALANCE_TOLERANCE_UVR:
        month = int(months[closing.argmin()])
        raise ValueError(f"The balance becomes negative ({closing.min():,.2f} UVR in month {month})")
    return pd.DataFrame(
        {
            "month": months,
            "opening_balance_uvr": opening,
            "interest_uvr": interest,
            "installment_uvr": installments,
            "prepayment_uvr": prepays,
            "total_payment_uvr": installments + prepays,
            "closing_balance_uvr": closing,
        }
    )


if __name__ == "__main__":
    table = schedule(load_assumptions()["loan"])
    final_balance = table["closing_balance_uvr"].iloc[-1]
    assert abs(final_balance) < 1e-6, f"Final balance is not zero: {final_balance}"

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    table.to_csv(OUTPUT_PATH, index=False)

    paid = table["installment_uvr"] > 0
    print(f"Monthly installment (UVR): {table.loc[paid, 'installment_uvr'].iloc[0]:,.4f}")
    print(f"Number of installments: {paid.sum()}")
    print(f"Final balance: {final_balance:.6f}")
    print(f"Written to {OUTPUT_PATH}")

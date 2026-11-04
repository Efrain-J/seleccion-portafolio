"""Decision dates and loan payments converted from UVR to COP.

Months are counted from t0: month 0 is t0 (Oct 2016) and month m is paid at the
end of calendar month t0 + m.
"""

from typing import Any

import pandas as pd

from uvr_loan.inflation import project_uvr


def decision_months(backtest: dict[str, Any]) -> list[int]:
    """Months tau = 0, k, 2k, ... at which the portfolio is reviewed (k = `review_every_months`)."""
    return list(range(0, backtest["horizon_months"], backtest["review_every_months"]))


def month_to_period(t0: str, month: int) -> pd.Period:
    return pd.Period(t0, "M") + month


def projected_payments_cop(
    schedule: pd.DataFrame,
    tau_month: int,
    uvr_tau: float,
    annual_inflation: float,
    horizon: int,
) -> pd.Series:
    """Payments of months tau+1 .. tau+horizon in COP, indexed by month."""
    payments = schedule.set_index("month")["total_payment_uvr"].loc[tau_month + 1 : tau_month + horizon]
    uvr = project_uvr(uvr_tau, annual_inflation, len(payments))
    return payments * uvr

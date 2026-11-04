"""Portfolio selection rules.

Plan 1 (conservative): the FIC holds the payments due before the next review,
the ETF a fixed share of the rest, and the remainder goes to a CDT that matures
at the next review. Run `python -m uvr_loan.portfolio` to print the allocation at t0.

Plan 2 (CDT ladder): a ladder of fixed-rate CDTs chosen with a linear program in UVR
that covers every remaining payment and maximizes the final wealth, using the expected
real return of each term.
"""

from collections.abc import Sequence
from typing import Any

import numpy as np
import pandas as pd
from scipy.optimize import linprog

from uvr_loan.amortization import schedule
from uvr_loan.cashflows import month_to_period, projected_payments_cop
from uvr_loan.config import load_assumptions
from uvr_loan.inflation import scenarios


def conservative_allocation(
    free_cop: float, payments_cop: Sequence[float], params: dict[str, Any]
) -> dict[str, float]:
    """Split the free money into FIC, CDT and ETF (COP).

    `uncovered_cop` is the part of the projected payments that the free money cannot cover
    (it is not a shortfall: shortfalls are only recorded when a payment is due).
    """
    needed = float(sum(payments_cop))
    fic = min(needed, free_cop)
    rest = free_cop - fic
    etf = params["etf_weight"] * rest
    return {"fic_cop": fic, "cdt_cop": rest - etf, "etf_cop": etf, "uncovered_cop": needed - fic}


def ladder_purchases(
    tau: int,
    budget_uvr: float,
    maturities_uvr: dict[int, float],
    payment_schedule: pd.DataFrame,
    cfg: dict[str, Any],
    cdt_real_ea: dict[int, float],
    fic_real_ea: float = 0.0,
) -> dict[int, float]:
    """UVR to invest today in a CDT of each term (months), from the LP solved at review `tau`.

    `cdt_real_ea` is the expected real annual return of a CDT of each term (its rate deflated
    by the expected inflation); `fic_real_ea` is the same for the cash in the FIC.

    Variables: purchases y[s, j] at the reviews s = tau, tau + k, ... (only if s + j <= H) and the
    cash c[m] at the close of each month m = tau .. H. Month balance (S12: maturities pay the
    same month): c[m] = c[m-1] * (1 + fic_real_ea)^(1/12) + matured CDTs + maturities_uvr[m]
    - y[m, :] - payment[m] >= 0. The objective maximizes c[H].
    """
    horizon, k = cfg["backtest"]["horizon_months"], cfg["backtest"]["review_every_months"]
    payments = payment_schedule.set_index("month")["total_payment_uvr"]

    lots = [(s, j) for s in range(tau, horizon + 1, k) for j in cdt_real_ea if s + j <= horizon]
    months = range(tau, horizon + 1)
    n_lots = len(lots)
    a_eq = np.zeros((len(months), n_lots + len(months)))
    b_eq = np.zeros(len(months))
    for row, m in enumerate(months):
        a_eq[row, n_lots + row] = 1.0  # c[m]
        if m > tau:
            a_eq[row, n_lots + row - 1] = -((1 + fic_real_ea) ** (1 / 12))  # c[m-1]
            b_eq[row] = maturities_uvr.get(m, 0.0) - payments.get(m, 0.0)
        else:
            b_eq[row] = budget_uvr
        for col, (s, j) in enumerate(lots):
            if s == m:
                a_eq[row, col] += 1.0
            if s + j == m:
                a_eq[row, col] -= (1 + cdt_real_ea[j]) ** (j / 12)

    objective = np.zeros(n_lots + len(months))
    objective[-1] = -1.0  # maximize c[H]
    result = linprog(objective, A_eq=a_eq, b_eq=b_eq, bounds=(0, None), method="highs")
    if result.status != 0:
        raise ValueError(f"No ladder covers the payments at month {tau}: {result.message}")

    buy = dict.fromkeys(cdt_real_ea, 0.0)
    for col, (s, j) in enumerate(lots):
        if s == tau:
            buy[j] = float(result.x[col])
    return buy


if __name__ == "__main__":
    from uvr_loan.data.cleaning import load_monthly_panel

    cfg = load_assumptions()
    params = cfg["conservative"]
    t0 = cfg["backtest"]["t0"]
    k = cfg["backtest"]["review_every_months"]

    history = load_monthly_panel(cfg).loc[: month_to_period(t0, 0)]
    row = history.iloc[-1]
    inflation = scenarios(cfg, history["uvr_cop"])[params["fic_sizing_scenario"]]
    payments = projected_payments_cop(schedule(cfg["loan"]), 0, row["uvr_cop"], inflation, k - 1)
    alloc = conservative_allocation(cfg["initial_capital_cop"], payments, params)

    print(f"Decision date: {t0}  (UVR {row['uvr_cop']:,.4f}, CDT 180d {row['cdt_180d_ea']:.2%})")
    print(
        f"Payments of the next {k - 1} months ({params['fic_sizing_scenario']} inflation {inflation:.2%}): "
        f"{sum(payments):,.0f}"
    )
    for name, amount in alloc.items():
        print(f"  {name:<14} {amount:>16,.0f} COP")

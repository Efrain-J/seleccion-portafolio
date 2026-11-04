"""Portfolio selection rules.

Plan 1 (conservative): the FIC holds the payments due before the new CDT matures
plus a fixed share of the rest, and the remainder goes to a CDT that matures at the
next review. There is no ETF. Run `python -m uvr_loan.portfolio` to print the allocation at t0.

Plan 2 (CDT ladder): a ladder of fixed-rate CDTs chosen with a linear program in UVR
that covers every remaining payment and maximizes the final wealth, using the expected
real return of each term.

Plan 3 (LDI): the floor is the smallest budget of that same LP (`ladder_floor`); the ladder
gets (1 + buffer) x floor and the rest goes to ETFs split by inverse volatility.
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
    """Split the free money between FIC and CDT (COP).

    The FIC holds the projected payments plus (1 - `cdt_weight`) of what is left; the CDT
    takes `cdt_weight` of what is left. `uncovered_cop` is the part of the projected payments
    that the free money cannot cover (it is not a shortfall: shortfalls are only recorded
    when a payment is due).
    """
    needed = float(sum(payments_cop))
    liquidity = min(needed, free_cop)
    cdt = params["cdt_weight"] * (free_cop - liquidity)
    return {"fic_cop": free_cop - cdt, "cdt_cop": cdt, "uncovered_cop": needed - liquidity}


def _solve(objective, a_eq, b_eq, tau, a_ub=None, b_ub=None):
    """Solve the ladder LP. Infeasible (status 2) raises ValueError: no ladder covers the payments.
    Any other solver failure raises RuntimeError, so it is not mistaken for an infeasible review."""
    result = linprog(objective, A_ub=a_ub, b_ub=b_ub, A_eq=a_eq, b_eq=b_eq, bounds=(0, None), method="highs")
    if result.status == 2:
        raise ValueError(f"No ladder covers the payments at month {tau}: {result.message}")
    if result.status != 0:
        raise RuntimeError(f"Ladder LP failed at month {tau}: {result.message}")
    return result


def _ladder_constraints(
    tau: int,
    maturities_uvr: dict[int, float],
    payment_schedule: pd.DataFrame,
    cfg: dict[str, Any],
    cdt_real_ea: dict[int, float],
    fic_real_ea: float,
) -> tuple[list[tuple[int, int]], np.ndarray, np.ndarray]:
    """Month balances of the ladder LP: (lots, a_eq, b_eq), with columns [y lots..., c[tau..H]].

    Row 0 is the review month: c[tau] + y[tau, :] = budget; its right-hand side is left at 0
    for the caller to fill. Rows m > tau: c[m] = c[m-1] * (1 + fic_real_ea)^(1/12) + matured CDTs
    + maturities_uvr[m] - y[m, :] - payment[m] (S12: maturities pay the same month).
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
        for col, (s, j) in enumerate(lots):
            if s == m:
                a_eq[row, col] += 1.0
            if s + j == m:
                a_eq[row, col] -= (1 + cdt_real_ea[j]) ** (j / 12)
    return lots, a_eq, b_eq


def ladder_floor(
    tau: int,
    maturities_uvr: dict[int, float],
    payment_schedule: pd.DataFrame,
    cfg: dict[str, Any],
    cdt_real_ea: dict[int, float],
    fic_real_ea: float = 0.0,
) -> float:
    """Floor of plan 3 (UVR): the smallest budget with which a ladder covers every remaining payment.

    Same constraints as `ladder_purchases`, with the budget B as one more variable
    (c[tau] + y[tau, :] - B = 0) and the objective min B.
    """
    _, a_eq, b_eq = _ladder_constraints(tau, maturities_uvr, payment_schedule, cfg, cdt_real_ea, fic_real_ea)
    budget = np.zeros((len(b_eq), 1))
    budget[0, 0] = -1.0
    objective = np.zeros(a_eq.shape[1] + 1)
    objective[-1] = 1.0
    floor = float(_solve(objective, np.hstack([a_eq, budget]), b_eq, tau).x[-1])
    # When the live CDTs already cover every payment the floor is 0, and the solver can return -0.0
    # (or a tiny negative); a negative floor would make no sense.
    return max(floor, 0.0) + 0.0


def inverse_volatility_weights(vols: dict[str, float]) -> dict[str, float]:
    """Weights proportional to 1 / volatility; with two assets each one contributes the same risk."""
    inverse = {name: 1 / vol for name, vol in vols.items()}
    total = sum(inverse.values())
    return {name: value / total for name, value in inverse.items()}


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
    cash c[m] at the close of each month m = tau .. H (constraints in `_ladder_constraints`).
    The objective maximizes c[H]; ties are broken toward the shortest terms (second stage).
    """
    lots, a_eq, b_eq = _ladder_constraints(
        tau, maturities_uvr, payment_schedule, cfg, cdt_real_ea, fic_real_ea
    )
    n_lots = len(lots)
    b_eq[0] = budget_uvr

    # Stage 1: the maximum final cash c[H].
    objective = np.zeros(a_eq.shape[1])
    objective[-1] = -1.0
    result = _solve(objective, a_eq, b_eq, tau)

    # Stage 2 (tie-break): among the solutions that reach that c[H], today's purchases with the
    # shortest terms (minimum sum of amount x term over y[tau, :]; future purchases are decided
    # again at each review), so the executed purchase does not depend on the solver.
    best = result.x[-1]
    floor = np.zeros(a_eq.shape[1])
    floor[-1] = -1.0  # -c[H] <= -(best - tolerance)
    shortest = np.zeros(a_eq.shape[1])
    shortest[:n_lots] = [j if s == tau else 0.0 for s, j in lots]
    tolerance = 1e-9 * max(1.0, abs(best))
    result = _solve(shortest, a_eq, b_eq, tau, a_ub=floor[None, :], b_ub=[-(best - tolerance)])

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

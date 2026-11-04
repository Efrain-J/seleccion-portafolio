"""Monthly backtest of the investment plans with dynamic reviews every k months.

Each month (S12): the FIC grows at last month's rate, the CDTs that mature move to the
FIC, and then the loan payment is taken from the FIC (what is missing is recorded as
shortfall, nothing is sold: S9). At each review the free money (FIC + ETF) is
reallocated by the plan's strategy; live CDTs are held to maturity (S13).

Run `python -m uvr_loan.backtest` to write the results of every plan to results/.
"""

from typing import Any

import numpy as np
import pandas as pd

from uvr_loan.amortization import schedule
from uvr_loan.cashflows import decision_months, month_to_period, projected_payments_cop
from uvr_loan.config import RESULTS_DIR, load_assumptions
from uvr_loan.inflation import project_uvr, scenarios
from uvr_loan.portfolio import conservative_allocation, ladder_purchases

# A fixed-rate CDT lot: `units` COP bought in month `bought` at the annual `rate`, paid in `matures`.
Lot = dict[str, Any]


def lot_value(lot: Lot, month: int) -> float:
    """Accrued value in COP of a lot at `month`."""
    return lot["units"] * (1 + lot["rate"]) ** ((month - lot["bought"]) / 12)


def conservative_strategy(
    tau: int,
    history: pd.DataFrame,
    free: float,
    lots: list[Lot],
    payment_schedule: pd.DataFrame,
    cfg: dict[str, Any],
) -> tuple[float, float, list[Lot]]:
    """Plan 1. Its CDT matures exactly at the next review, so no lot is alive at a review."""
    params, k = cfg["conservative"], cfg["backtest"]["rebalance_every"]
    row = history.iloc[-1]
    inflation = scenarios(cfg, history["uvr"])[params["liquidity_scenario"]]
    projected = projected_payments_cop(payment_schedule, tau, row["uvr"], inflation, k)
    alloc = conservative_allocation(free, projected, params)
    cdt = {"units": alloc["cdt"], "rate": row["cdt_180"], "bought": tau, "matures": tau + k}
    return alloc["fic"], alloc["etf"], [cdt]


def cdt_ladder_strategy(
    tau: int,
    history: pd.DataFrame,
    free: float,
    lots: list[Lot],
    payment_schedule: pd.DataFrame,
    cfg: dict[str, Any],
) -> tuple[float, float, list[Lot]]:
    """Plan 2: ladder of fixed-rate CDTs from the LP in UVR.

    The LP decides with expected real returns: each nominal rate of tau (CDT terms and FIC)
    deflated by the inflation of `liquidity_scenario`. Live lots enter as known maturities,
    converted to UVR with the projected UVR. If no ladder covers every payment, nothing is
    bought and the money stays in the FIC (S9 records the shortfalls).
    """
    params = cfg["cdt_ladder"]
    terms = {int(j): column for j, column in params["terms"].items()}
    row = history.iloc[-1]
    inflation = scenarios(cfg, history["uvr"])[params["liquidity_scenario"]]

    def real(rate: float) -> float:
        return (1 + rate) / (1 + inflation) - 1

    maturities: dict[int, float] = {}
    for lot in lots:
        uvr_then = project_uvr(row["uvr"], inflation, lot["matures"] - tau)[-1]
        maturities[lot["matures"]] = (
            maturities.get(lot["matures"], 0.0) + lot_value(lot, lot["matures"]) / uvr_then
        )
    real_rates = {j: real(row[column]) for j, column in terms.items()}
    try:
        buy = ladder_purchases(
            tau, free / row["uvr"], maturities, payment_schedule, cfg, real_rates, real(row["fic"])
        )
    except ValueError:
        return free, 0.0, []
    new = [
        {"units": units * row["uvr"], "rate": row[terms[j]], "bought": tau, "matures": tau + j}
        for j, units in buy.items()
        if units > 0
    ]
    # The solver tolerance can spend a fraction of a peso more than `free`.
    return max(free - sum(buy.values()) * row["uvr"], 0.0), 0.0, new


STRATEGIES = {"conservative": conservative_strategy, "cdt_ladder": cdt_ladder_strategy}


def run_backtest(
    panel: pd.DataFrame, payment_schedule: pd.DataFrame, cfg: dict[str, Any], strategy: str = "conservative"
) -> pd.DataFrame:
    """One row per month 0..horizon with the payment, shortfall and value of each asset in COP."""
    bt = cfg["backtest"]
    reviews = set(decision_months(bt))
    payments_uvr = payment_schedule.set_index("month")["total_payment_uvr"]
    allocate = STRATEGIES[strategy]

    fic, etf_units, lots = float(cfg["initial_capital_cop"]), 0.0, []
    rows = []
    for m in range(bt["horizon_months"] + 1):
        row = panel.loc[month_to_period(bt["t0"], m)]
        payment = shortfall = 0.0
        if m > 0:
            fic *= (1 + panel.loc[month_to_period(bt["t0"], m - 1), "fic"]) ** (1 / 12)
            fic += sum(lot_value(lot, m) for lot in lots if lot["matures"] == m)
            lots = [lot for lot in lots if lot["matures"] != m]
            payment = payments_uvr.get(m, 0.0) * row["uvr"]
            shortfall = max(payment - fic, 0.0)
            fic -= payment - shortfall

        if m in reviews:
            free = fic + etf_units * row["etf"]
            history = panel.loc[: month_to_period(bt["t0"], m)]  # only data known at the review
            fic, etf, new_lots = allocate(m, history, free, lots, payment_schedule, cfg)
            etf_units = etf / row["etf"]
            lots += new_lots

        etf = etf_units * row["etf"]
        cdt = sum(lot_value(lot, m) for lot in lots)
        rows.append(
            {
                "month": m,
                "period": str(month_to_period(bt["t0"], m)),
                "uvr": row["uvr"],
                "payment_cop": payment,
                "shortfall": shortfall,
                "fic": fic,
                "cdt": cdt,
                "etf": etf,
                "wealth": fic + cdt + etf,
                "review": m in reviews,
            }
        )
    return pd.DataFrame(rows)


def summary(results: pd.DataFrame) -> dict[str, float]:
    """Shortfalls, liquidity and time-weighted return metrics (payments are not counted as losses)."""
    paid = results["payment_cop"] - results["shortfall"]
    monthly = ((results["wealth"] + paid) / results["wealth"].shift() - 1).iloc[1:]
    growth = (1 + monthly).cumprod()
    return {
        "shortfall_months": int((results["shortfall"] > 0).sum()),
        "total_shortfall_cop": results["shortfall"].sum(),
        "min_liquidity_cop": results.loc[results["payment_cop"] > 0, "fic"].min(),
        "final_wealth_cop": results["wealth"].iloc[-1],
        "annual_return": growth.iloc[-1] ** (12 / len(monthly)) - 1,
        "annual_volatility": monthly.std() * np.sqrt(12),
        "max_drawdown": (1 - growth / growth.cummax()).max(),
    }


if __name__ == "__main__":
    from uvr_loan.data.cleaning import load_monthly_panel

    cfg = load_assumptions()
    panel, payment_schedule = load_monthly_panel(cfg), schedule(cfg["loan"])
    RESULTS_DIR.mkdir(exist_ok=True)

    metrics = {}
    for name in STRATEGIES:
        results = run_backtest(panel, payment_schedule, cfg, name)
        results.to_csv(RESULTS_DIR / f"backtest_{name}.csv", index=False)
        metrics[name] = summary(results)

    table = pd.DataFrame(metrics)
    table.to_csv(RESULTS_DIR / "summary.csv", index_label="metric")
    print(table.to_string(float_format=lambda x: f"{x:,.4f}"))
    print(f"Written to {RESULTS_DIR}")

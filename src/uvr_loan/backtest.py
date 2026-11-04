"""Monthly backtest of the investment plans with dynamic reviews every k months.

Each month (S12): the FIC grows with the realized return of the FIC index, the CDTs that
mature move to the FIC, and then the loan payment is taken from the liquidity: first the FIC,
then ETF units sold at the price of the month; what is still missing is recorded as shortfall
(S9). CDTs are never redeemed early. At each review the free money (FIC + ETF) is reallocated
by the plan's strategy; live CDTs are held to maturity (S13).

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

# A fixed-rate CDT lot: `principal_cop` bought in month `buy_month` at the annual `rate_ea`,
# paid in `maturity_month`.
Lot = dict[str, Any]


def lot_value(lot: Lot, month: int) -> float:
    """Accrued value in COP of a lot at `month`."""
    return lot["principal_cop"] * (1 + lot["rate_ea"]) ** ((month - lot["buy_month"]) / 12)


def conservative_strategy(
    tau: int,
    history: pd.DataFrame,
    free_cop: float,
    lots: list[Lot],
    payment_schedule: pd.DataFrame,
    cfg: dict[str, Any],
) -> tuple[float, float, list[Lot]]:
    """Plan 1. Its CDT matures exactly at the next review, so no lot is alive at a review.

    The FIC holds the payments of months tau+1 .. tau+k-1 (the CDT matures in month tau+k and
    pays that month, S12) plus (1 - `cdt_weight`) of the rest. During the grace period
    (tau < `grace_months`) `grace_cdt_weight` is used instead. There is no ETF.
    """
    params, k = cfg["conservative"], cfg["backtest"]["review_every_months"]
    row = history.iloc[-1]
    inflation = scenarios(cfg, history["uvr_cop"])[params["fic_sizing_scenario"]]
    projected = projected_payments_cop(payment_schedule, tau, row["uvr_cop"], inflation, k - 1)
    if tau < cfg["loan"]["grace_months"]:  # no payments yet: the FIC share also goes to the CDT
        params = {**params, "cdt_weight": params["grace_cdt_weight"]}
    alloc = conservative_allocation(free_cop, projected, params)
    cdt = {
        "principal_cop": alloc["cdt_cop"],
        "rate_ea": row["cdt_180d_ea"],
        "buy_month": tau,
        "maturity_month": tau + k,
    }
    return alloc["fic_cop"], 0.0, [cdt]


def cdt_ladder_strategy(
    tau: int,
    history: pd.DataFrame,
    free_cop: float,
    lots: list[Lot],
    payment_schedule: pd.DataFrame,
    cfg: dict[str, Any],
) -> tuple[float, float, list[Lot]]:
    """Plan 2: ladder of fixed-rate CDTs from the LP in UVR.

    The LP decides with expected real returns: each nominal rate of tau (CDT terms and FIC)
    deflated by the inflation of `deflator_scenario`. Live lots enter as known maturities,
    converted to UVR with the projected UVR. If no ladder covers every payment, nothing is
    bought and the money stays in the FIC (S9 records the shortfalls).
    """
    params = cfg["cdt_ladder"]
    terms = {int(j): column for j, column in params["term_columns"].items()}
    row = history.iloc[-1]
    inflation = scenarios(cfg, history["uvr_cop"])[params["deflator_scenario"]]

    def real(rate: float) -> float:
        return (1 + rate) / (1 + inflation) - 1

    maturities: dict[int, float] = {}
    for lot in lots:
        due = lot["maturity_month"]
        uvr_then = project_uvr(row["uvr_cop"], inflation, due - tau)[-1]
        maturities[due] = maturities.get(due, 0.0) + lot_value(lot, due) / uvr_then
    cdt_real_ea = {j: real(row[column]) for j, column in terms.items()}
    try:
        buy_uvr = ladder_purchases(
            tau,
            free_cop / row["uvr_cop"],
            maturities,
            payment_schedule,
            cfg,
            cdt_real_ea,
            real(row["fic_rate_ea"]),
        )
    except ValueError:
        return free_cop, 0.0, []
    new = [
        {
            "principal_cop": amount_uvr * row["uvr_cop"],
            "rate_ea": row[terms[j]],
            "buy_month": tau,
            "maturity_month": tau + j,
        }
        for j, amount_uvr in buy_uvr.items()
        if amount_uvr > 0
    ]
    # The solver tolerance can spend a fraction of a peso more than `free_cop`.
    return max(free_cop - sum(buy_uvr.values()) * row["uvr_cop"], 0.0), 0.0, new


PLANS = {"conservative": conservative_strategy, "cdt_ladder": cdt_ladder_strategy}


def run_backtest(
    panel: pd.DataFrame, payment_schedule: pd.DataFrame, cfg: dict[str, Any], plan: str = "conservative"
) -> pd.DataFrame:
    """One row per month 0..horizon with the payment, shortfall and value of each asset in COP."""
    bt = cfg["backtest"]
    reviews = set(decision_months(bt))
    payments_uvr = payment_schedule.set_index("month")["total_payment_uvr"]
    allocate = PLANS[plan]

    fic, etf_units, lots = float(cfg["initial_capital_cop"]), 0.0, []
    rows = []
    for m in range(bt["horizon_months"] + 1):
        row = panel.loc[month_to_period(bt["t0"], m)]
        payment = shortfall = etf_sold = 0.0
        if m > 0:
            fic *= 1 + row["fic_ret_m"]  # realized return of the FIC index in month m
            fic += sum(lot_value(lot, m) for lot in lots if lot["maturity_month"] == m)
            lots = [lot for lot in lots if lot["maturity_month"] != m]
            payment = payments_uvr.get(m, 0.0) * row["uvr_cop"]
            shortfall = max(payment - fic, 0.0)
            fic -= payment - shortfall
            etf_sold = min(shortfall, etf_units * row["etf_price_cop"])  # the ETF covers what the FIC can't
            etf_units -= etf_sold / row["etf_price_cop"]
            shortfall -= etf_sold

        if m in reviews:
            free_cop = fic + etf_units * row["etf_price_cop"]
            history = panel.loc[: month_to_period(bt["t0"], m)]  # only data known at the review
            fic, etf, new_lots = allocate(m, history, free_cop, lots, payment_schedule, cfg)
            etf_units = etf / row["etf_price_cop"]
            lots += new_lots

        etf = etf_units * row["etf_price_cop"]
        cdt = sum(lot_value(lot, m) for lot in lots)
        rows.append(
            {
                "month": m,
                "period": str(month_to_period(bt["t0"], m)),
                "uvr_cop": row["uvr_cop"],
                "payment_cop": payment,
                "shortfall_cop": shortfall,
                "etf_sold_cop": etf_sold,
                "fic_cop": fic,
                "cdt_cop": cdt,
                "etf_cop": etf,
                "wealth_cop": fic + cdt + etf,
                "is_review": m in reviews,
            }
        )
    results = pd.DataFrame(rows)
    # An unpaid payment is still owed: the net wealth deducts every shortfall so far.
    results["wealth_net_cop"] = results["wealth_cop"] - results["shortfall_cop"].cumsum()
    return results


def summary(results: pd.DataFrame) -> dict[str, float]:
    """Shortfalls, liquidity (FIC + ETF) and time-weighted return metrics (payments are not losses)."""
    paid = results["payment_cop"] - results["shortfall_cop"]
    monthly = ((results["wealth_cop"] + paid) / results["wealth_cop"].shift() - 1).iloc[1:]
    growth = (1 + monthly).cumprod()
    return {
        "shortfall_months": int((results["shortfall_cop"] > 0).sum()),
        "total_shortfall_cop": results["shortfall_cop"].sum(),
        "min_liquid_at_payment_cop": (results["fic_cop"] + results["etf_cop"])[
            results["payment_cop"] > 0
        ].min(),
        "total_etf_sold_cop": results["etf_sold_cop"].sum(),
        "final_wealth_cop": results["wealth_cop"].iloc[-1],
        "final_wealth_net_cop": results["wealth_net_cop"].iloc[-1],
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
    for name in PLANS:
        results = run_backtest(panel, payment_schedule, cfg, name)
        results.to_csv(RESULTS_DIR / f"backtest_{name}.csv", index=False)
        metrics[name] = summary(results)

    table = pd.DataFrame(metrics)
    table.to_csv(RESULTS_DIR / "summary.csv", index_label="metric")
    print(table.to_string(float_format=lambda x: f"{x:,.4f}"))
    print(f"Written to {RESULTS_DIR}")

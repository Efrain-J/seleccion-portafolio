"""Monthly backtest of the conservative plan with dynamic reviews every k months.

Each month: the FIC grows at last month's rate, the CDT at the rate locked when it
was bought and the ETF with its price; then the loan payment is taken from the FIC
(what is missing is recorded as shortfall, nothing is sold). At each review the
whole portfolio is reallocated with `conservative_allocation`.

Run `python -m uvr_loan.backtest` to write the results to results/.
"""

from typing import Any

import numpy as np
import pandas as pd

from uvr_loan.amortization import schedule
from uvr_loan.cashflows import decision_months, month_to_period, projected_payments_cop
from uvr_loan.config import RESULTS_DIR, load_assumptions
from uvr_loan.inflation import scenarios
from uvr_loan.portfolio import conservative_allocation


def run_backtest(panel: pd.DataFrame, payment_schedule: pd.DataFrame, cfg: dict[str, Any]) -> pd.DataFrame:
    """One row per month 0..horizon with the payment, shortfall and value of each asset in COP."""
    bt, params = cfg["backtest"], cfg["conservative"]
    k = bt["rebalance_every"]
    reviews = set(decision_months(bt))
    payments_uvr = payment_schedule.set_index("month")["total_payment_uvr"]
    inflation = scenarios(cfg)[params["liquidity_scenario"]]

    fic, cdt, etf_units, cdt_rate = float(cfg["initial_capital_cop"]), 0.0, 0.0, 0.0
    rows = []
    for m in range(bt["horizon_months"] + 1):
        row = panel.loc[month_to_period(bt["t0"], m)]
        payment = shortfall = 0.0
        if m > 0:
            fic *= (1 + panel.loc[month_to_period(bt["t0"], m - 1), "fic"]) ** (1 / 12)
            cdt *= (1 + cdt_rate) ** (1 / 12)
            payment = payments_uvr.get(m, 0.0) * row["uvr"]
            shortfall = max(payment - fic, 0.0)
            fic -= payment - shortfall

        if m in reviews:
            wealth = fic + cdt + etf_units * row["etf"]
            projected = projected_payments_cop(payment_schedule, m, row["uvr"], inflation, k)
            alloc = conservative_allocation(wealth, projected, params)
            fic, cdt, etf_units = alloc["fic"], alloc["cdt"], alloc["etf"] / row["etf"]
            cdt_rate = row["cdt_180"]

        etf = etf_units * row["etf"]
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
    results = run_backtest(load_monthly_panel(cfg), schedule(cfg["loan"]), cfg)
    metrics = pd.Series(summary(results), name="value")

    RESULTS_DIR.mkdir(exist_ok=True)
    results.to_csv(RESULTS_DIR / "backtest_conservative.csv", index=False)
    metrics.to_csv(RESULTS_DIR / "summary_conservative.csv", index_label="metric")
    print(metrics.to_string(float_format=lambda x: f"{x:,.4f}"))
    print(f"Written to {RESULTS_DIR}")

"""Portfolio selection rules.

Plan 1 (conservative): the FIC holds the payments due before the next review,
the ETF a fixed share of the rest, and the remainder goes to a CDT that matures
at the next review. Run `python -m uvr_loan.portfolio` to print the allocation at t0.
"""

from collections.abc import Sequence
from typing import Any

from uvr_loan.amortization import schedule
from uvr_loan.cashflows import month_to_period, projected_payments_cop
from uvr_loan.config import load_assumptions
from uvr_loan.inflation import scenarios


def conservative_allocation(
    wealth: float, payments_cop: Sequence[float], params: dict[str, Any]
) -> dict[str, float]:
    """Amounts in COP for `fic`, `cdt` and `etf`, plus the uncovered `shortfall`."""
    needed = float(sum(payments_cop))
    fic = min(needed, wealth)
    rest = wealth - fic
    etf = params["equity_weight"] * rest
    return {"fic": fic, "cdt": rest - etf, "etf": etf, "shortfall": needed - fic}


if __name__ == "__main__":
    from uvr_loan.data.cleaning import load_monthly_panel

    cfg = load_assumptions()
    params = cfg["conservative"]
    t0 = cfg["backtest"]["t0"]
    k = cfg["backtest"]["rebalance_every"]

    panel = load_monthly_panel(cfg)
    row = panel.loc[month_to_period(t0, 0)]
    inflation = scenarios(cfg)[params["liquidity_scenario"]]
    payments = projected_payments_cop(schedule(cfg["loan"]), 0, row["uvr"], inflation, k)
    alloc = conservative_allocation(cfg["initial_capital_cop"], payments, params)

    print(f"Decision date: {t0}  (UVR {row['uvr']:,.4f}, CDT 180d {row['cdt_180']:.2%})")
    print(
        f"Payments next {k} months ({params['liquidity_scenario']} inflation {inflation:.2%}): {sum(payments):,.0f}"
    )
    for name, amount in alloc.items():
        print(f"  {name:<9} {amount:>16,.0f} COP")

"""Monthly backtest of the investment plans with dynamic reviews every k months.

Each month (S12): the FIC grows with the realized return of the FIC index, the CDTs that
mature move to the FIC, and then the loan payment is taken from the liquidity: first the FIC,
then ETF units sold at the price of the month; what is still missing is recorded as shortfall
(S9). CDTs are never redeemed early. At each review the free money (FIC + ETF) is reallocated
by the plan's strategy; live CDTs are held to maturity (S13). There can be several ETFs (one per
entry of `data.etfs` in the config, priced with the panel column `<name>_price_cop`); when they
must cover a payment, each one is sold in proportion to its value.

Plan 4 (`trend_ldi`) is plan 3 with a trend filter: an ETF with a negative return over the last
months gets no money at a review, and its share stays in the FIC.

Run `python -m uvr_loan.backtest` to write the results of every plan to results/backtest/.
"""

from typing import Any, NamedTuple

import numpy as np
import pandas as pd

from uvr_loan.amortization import schedule
from uvr_loan.cashflows import decision_months, month_to_period, projected_payments_cop
from uvr_loan.config import BACKTEST_DIR, load_assumptions
from uvr_loan.inflation import project_uvr, scenarios
from uvr_loan.portfolio import (
    conservative_allocation,
    inverse_volatility_weights,
    ladder_floor,
    ladder_purchases,
    payments_by_month,
)

# A fixed-rate CDT lot: `principal_cop` bought in month `buy_month` at the annual `rate_ea`,
# paid in `maturity_month`.
Lot = dict[str, Any]

# Panel column with the price in COP of an ETF of `data.etfs`: `<name>_price_cop`.
PRICE_SUFFIX = "_price_cop"


class Allocation(NamedTuple):
    """What a strategy decides at a review (COP): the FIC, the money in each ETF (by name), the new
    CDT lots and, for plan 3, the floor."""

    fic_cop: float
    etf_cop: dict[str, float]
    lots: list[Lot]
    floor_cop: float = float("nan")


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
) -> Allocation:
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
    return Allocation(alloc["fic_cop"], {}, [cdt])


def _cdt_terms(cfg: dict[str, Any]) -> dict[int, str]:
    """CDT term in months: panel column with its rate (`cdt_ladder.term_columns`, used by plans 2 and 3)."""
    return {int(j): column for j, column in cfg["cdt_ladder"]["term_columns"].items()}


def _ladder_inputs(
    tau: int, history: pd.DataFrame, lots: list[Lot], cfg: dict[str, Any], scenario: str
) -> tuple[dict[int, float], dict[int, float], float]:
    """Inputs of the ladder LP at review tau, with the inflation of `scenario`.

    Returns the maturities of the live lots in UVR (converted with the projected UVR) and the
    expected real annual return of each CDT term and of the FIC (nominal rate of tau deflated).
    """
    terms = _cdt_terms(cfg)
    row = history.iloc[-1]
    inflation = scenarios(cfg, history["uvr_cop"])[scenario]

    def real(rate: float) -> float:
        return (1 + rate) / (1 + inflation) - 1

    maturities: dict[int, float] = {}
    for lot in lots:
        due = lot["maturity_month"]
        uvr_then = project_uvr(row["uvr_cop"], inflation, due - tau)[-1]
        maturities[due] = maturities.get(due, 0.0) + lot_value(lot, due) / uvr_then
    cdt_real_ea = {j: real(row[column]) for j, column in terms.items()}
    return maturities, cdt_real_ea, real(row["fic_rate_ea"])


def _bought_lots(tau: int, row: pd.Series, buy_uvr: dict[int, float], cfg: dict[str, Any]) -> list[Lot]:
    """CDT lots for the LP purchases of review tau, at the observed rate of each term."""
    terms = _cdt_terms(cfg)
    return [
        {
            "principal_cop": amount_uvr * row["uvr_cop"],
            "rate_ea": row[terms[j]],
            "buy_month": tau,
            "maturity_month": tau + j,
        }
        for j, amount_uvr in buy_uvr.items()
        if amount_uvr > 0
    ]


def cdt_ladder_strategy(
    tau: int,
    history: pd.DataFrame,
    free_cop: float,
    lots: list[Lot],
    payment_schedule: pd.DataFrame,
    cfg: dict[str, Any],
) -> Allocation:
    """Plan 2: ladder of fixed-rate CDTs from the LP in UVR.

    The LP decides with expected real returns: each nominal rate of tau (CDT terms and FIC)
    deflated by the inflation of `deflator_scenario`. Live lots enter as known maturities,
    converted to UVR with the projected UVR. If no ladder covers every payment, nothing is
    bought and the money stays in the FIC (S9 records the shortfalls).
    """
    row = history.iloc[-1]
    maturities, cdt_real_ea, fic_real_ea = _ladder_inputs(
        tau, history, lots, cfg, cfg["cdt_ladder"]["deflator_scenario"]
    )
    try:
        buy_uvr = ladder_purchases(
            tau, free_cop / row["uvr_cop"], maturities, payment_schedule, cfg, cdt_real_ea, fic_real_ea
        )
    except ValueError:
        return Allocation(free_cop, {}, [])
    # The solver tolerance can spend a fraction of a peso more than `free_cop`.
    fic = max(free_cop - sum(buy_uvr.values()) * row["uvr_cop"], 0.0)
    return Allocation(fic, {}, _bought_lots(tau, row, buy_uvr, cfg))


def ldi_strategy(
    tau: int,
    history: pd.DataFrame,
    free_cop: float,
    lots: list[Lot],
    payment_schedule: pd.DataFrame,
    cfg: dict[str, Any],
) -> Allocation:
    """Plan 3: CDT ladder up to the floor, ETFs with the rest (CPPI with m = 1).

    The floor is the smallest ladder budget that covers every remaining payment (`ladder_floor`),
    with the inflation of `floor_scenario` and live lots as known maturities. The ladder LP gets
    (1 + `floor_buffer`) x floor, or all the free money if it is less; the rest goes to the ETFs of
    `growth_assets`, split by inverse volatility. A fall of the ETFs never touches the ladder. If the
    free money is below the floor, no ladder is possible: the money stays in the FIC, as in plan 2.
    The ladder buys the same CDT terms as plan 2 (`cdt_ladder.term_columns`).
    """
    params = cfg["ldi"]
    row = history.iloc[-1]
    uvr = row["uvr_cop"]
    maturities, cdt_real_ea, fic_real_ea = _ladder_inputs(tau, history, lots, cfg, params["floor_scenario"])
    floor_uvr = ladder_floor(tau, maturities, payment_schedule, cfg, cdt_real_ea, fic_real_ea)
    ladder_uvr = min(free_cop / uvr, (1 + params["floor_buffer"]) * floor_uvr)
    try:
        buy_uvr = ladder_purchases(
            tau, ladder_uvr, maturities, payment_schedule, cfg, cdt_real_ea, fic_real_ea
        )
    except ValueError:
        buy_uvr = {}
    growth_cop = free_cop - ladder_uvr * uvr
    weights = inverse_volatility_weights({name: row[f"{name}_vol_ea"] for name in params["growth_assets"]})
    # The solver tolerance can spend a fraction of a peso more than the ladder budget.
    fic = max(ladder_uvr * uvr - sum(buy_uvr.values()) * uvr, 0.0)
    etfs = {name: growth_cop * w for name, w in weights.items()}
    return Allocation(fic, etfs, _bought_lots(tau, row, buy_uvr, cfg), floor_cop=floor_uvr * uvr)


def trend_ldi_strategy(
    tau: int,
    history: pd.DataFrame,
    free_cop: float,
    lots: list[Lot],
    payment_schedule: pd.DataFrame,
    cfg: dict[str, Any],
) -> Allocation:
    """Plan 4: plan 3 with a trend filter on the ETFs.

    Same floor, ladder and inverse-volatility split as `ldi_strategy`. An ETF whose return of the last
    `data.trend_window_months` months (`<name>_trend_ret`, known at tau) is below
    `trend_ldi.min_trailing_return` gets no money: its share stays in the FIC, it is not given to the
    other ETFs. The filter is evaluated again at every review.
    """
    alloc = ldi_strategy(tau, history, free_cop, lots, payment_schedule, cfg)
    row, minimum = history.iloc[-1], cfg["trend_ldi"]["min_trailing_return"]
    kept = {name: cop for name, cop in alloc.etf_cop.items() if row[f"{name}_trend_ret"] >= minimum}
    left_out = sum(alloc.etf_cop.values()) - sum(kept.values())
    return alloc._replace(fic_cop=alloc.fic_cop + left_out, etf_cop=kept)


PLANS = {
    "conservative": conservative_strategy,
    "cdt_ladder": cdt_ladder_strategy,
    "ldi": ldi_strategy,
    "trend_ldi": trend_ldi_strategy,
}


def total_funding_ratio(free_cop: float, live_cdt_cop: float, floor_cop: float) -> float:
    """(free money + live CDTs) / (floor + live CDTs), all in COP at a review.

    The floor only covers what the live CDTs do not, so adding their value on both sides gives the
    funding ratio of the whole portfolio. NaN for plans without a floor; inf if nothing is needed.
    """
    if np.isnan(floor_cop):
        return np.nan
    needed = floor_cop + live_cdt_cop
    return (free_cop + live_cdt_cop) / needed if needed > 0 else np.inf


def check_panel(panel: pd.DataFrame, backtest_cfg: dict[str, Any], price_columns: list[str]) -> None:
    """Raise ValueError if a month of the backtest (t0 .. t0 + horizon) is missing, has a missing
    value, or has an ETF price that is not positive: they would give NaN or inf results silently."""
    months = [month_to_period(backtest_cfg["t0"], m) for m in range(backtest_cfg["horizon_months"] + 1)]
    absent = [str(p) for p in months if p not in panel.index]
    if absent:
        raise ValueError(f"The panel has no data for months: {', '.join(absent)}")
    used = panel.loc[months]
    for column in used.columns:
        missing = used.index[used[column].isna()]
        if len(missing):
            raise ValueError(f"Missing values of {column} in months: {', '.join(map(str, missing))}")
    for column in price_columns:
        bad = used.index[used[column] <= 0]
        if len(bad):
            raise ValueError(
                f"Prices of {column} must be positive, not in months: {', '.join(map(str, bad))}"
            )


def run_backtest(
    panel: pd.DataFrame, payment_schedule: pd.DataFrame, cfg: dict[str, Any], plan: str = "conservative"
) -> pd.DataFrame:
    """One row per month 0..horizon with the payment, shortfall and value of each asset in COP.

    The ETFs are the entries of `data.etfs`, priced with the panel columns `<name>_price_cop`; each
    one gets a `<name>_cop` column and `etf_cop` is their total. At reviews, `floor_cop` and
    `funding_ratio_total` (see `total_funding_ratio`) are recorded when the plan has a floor (NaN
    otherwise). Raises ValueError if the months of the backtest are not usable (`check_panel`).
    """
    bt = cfg["backtest"]
    reviews = set(decision_months(bt))
    payments_uvr = payments_by_month(payment_schedule, bt["horizon_months"])
    allocate = PLANS[plan]
    names = list(cfg["data"]["etfs"])
    check_panel(panel, bt, [name + PRICE_SUFFIX for name in names])
    # The columns used every month, as arrays indexed by month (pandas access per month is slow).
    periods = [month_to_period(bt["t0"], m) for m in range(bt["horizon_months"] + 1)]
    used = panel.loc[periods]
    fic_ret, uvr = used["fic_ret_m"].to_numpy(), used["uvr_cop"].to_numpy()
    price_arrays = {name: used[name + PRICE_SUFFIX].to_numpy() for name in names}

    fic, lots = float(cfg["initial_capital_cop"]), []
    units = dict.fromkeys(names, 0.0)
    rows = []
    for m in range(bt["horizon_months"] + 1):
        prices = {name: price_arrays[name][m] for name in names}
        payment = shortfall = etf_sold = 0.0
        if m > 0:
            fic *= 1 + fic_ret[m]  # realized return of the FIC index in month m
            fic += sum(lot_value(lot, m) for lot in lots if lot["maturity_month"] == m)
            lots = [lot for lot in lots if lot["maturity_month"] != m]
            payment = payments_uvr[m] * uvr[m]
            shortfall = max(payment - fic, 0.0)
            fic -= payment - shortfall
            etf_total = sum(units[n] * prices[n] for n in names)
            etf_sold = min(shortfall, etf_total)  # the ETFs cover what the FIC can't, each pro rata
            if etf_sold > 0:
                units = {n: u * (1 - etf_sold / etf_total) for n, u in units.items()}
            shortfall -= etf_sold

        floor = funding = np.nan
        if m in reviews:
            free_cop = fic + sum(units[n] * prices[n] for n in names)
            history = panel.loc[: periods[m]]  # only data known at the review
            alloc = allocate(m, history, free_cop, lots, payment_schedule, cfg)
            fic, floor = alloc.fic_cop, alloc.floor_cop
            funding = total_funding_ratio(free_cop, sum(lot_value(lot, m) for lot in lots), floor)
            units = dict.fromkeys(names, 0.0) | {n: cop / prices[n] for n, cop in alloc.etf_cop.items()}
            lots += alloc.lots

        etfs = {f"{n}_cop": units[n] * prices[n] for n in names}
        etf = sum(etfs.values())
        cdt = sum(lot_value(lot, m) for lot in lots)
        rows.append(
            {
                "month": m,
                "period": str(periods[m]),
                "uvr_cop": uvr[m],
                "payment_cop": payment,
                "shortfall_cop": shortfall,
                "etf_sold_cop": etf_sold,
                "fic_cop": fic,
                "cdt_cop": cdt,
                "etf_cop": etf,
                **etfs,
                "wealth_cop": fic + cdt + etf,
                "is_review": m in reviews,
                "floor_cop": floor,
                "funding_ratio_total": funding,
            }
        )
    results = pd.DataFrame(rows)
    # An unpaid payment is still owed: the net wealth deducts every shortfall so far.
    results["wealth_net_cop"] = results["wealth_cop"] - results["shortfall_cop"].cumsum()
    return results


def summary(results: pd.DataFrame) -> dict[str, float]:
    """Shortfalls, liquidity (FIC + ETFs) and time-weighted return metrics (payments are not losses)."""
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
        # The path starts at 1 in month 0, so a fall in the first month also counts.
        "max_drawdown": (1 - growth / np.maximum(growth.cummax(), 1.0)).max(),
    }


def main() -> None:
    from uvr_loan.data.cleaning import load_monthly_panel

    cfg = load_assumptions()
    panel, payment_schedule = load_monthly_panel(cfg), schedule(cfg["loan"])
    BACKTEST_DIR.mkdir(parents=True, exist_ok=True)

    metrics = {}
    for name in PLANS:
        results = run_backtest(panel, payment_schedule, cfg, name)
        results.to_csv(BACKTEST_DIR / f"{name}.csv", index=False)
        metrics[name] = summary(results)

    table = pd.DataFrame(metrics)
    table.to_csv(BACKTEST_DIR / "summary.csv", index_label="metric")
    print(table.to_string(float_format=lambda x: f"{x:,.4f}"))
    print(f"Written to {BACKTEST_DIR}")


if __name__ == "__main__":
    main()

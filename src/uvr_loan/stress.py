"""Stress test: the plans with ETFs when the ETFs perform badly.

Each scenario changes only the ETF prices from t0 on; rates, UVR, FIC and payments stay as they were.
`<name>_trend_ret` is updated with the new prices, so the trend filter of plan 4 sees them: with
f_m = new price / real price (1 before t0), 1 + new trend_m = (1 + real trend_m) * f_m / f_{m-w}, with
w = `data.trend_window_months`. The volatilities stay historical (they only change the split between ETFs).

Run `python -m uvr_loan.stress` to write results/stress_summary.csv.
"""

from typing import Any

import numpy as np
import pandas as pd

from uvr_loan.backtest import PRICE_SUFFIX, run_backtest, summary
from uvr_loan.cashflows import month_to_period


def _months(cfg: dict[str, Any]) -> list[pd.Period]:
    bt = cfg["backtest"]
    return [month_to_period(bt["t0"], m) for m in range(bt["horizon_months"] + 1)]


def with_prices(panel: pd.DataFrame, cfg: dict[str, Any], prices: dict[str, np.ndarray]) -> pd.DataFrame:
    """Copy of the panel with the prices of months t0 .. t0 + horizon of each ETF in `prices` replaced,
    and its `<name>_trend_ret` updated with the new prices."""
    new = panel.copy()
    months = _months(cfg)
    for name, price in prices.items():
        column = name + PRICE_SUFFIX
        factor = pd.Series(1.0, index=panel.index)
        factor[months] = np.asarray(price) / panel.loc[months, column].to_numpy()
        new.loc[months, column] = price
        before = factor.shift(cfg["data"]["trend_window_months"]).fillna(1.0)
        new[f"{name}_trend_ret"] = (1 + panel[f"{name}_trend_ret"]) * factor / before - 1
    return new


def drift_down(panel: pd.DataFrame, cfg: dict[str, Any], final_ratio: float) -> pd.DataFrame:
    """Each ETF keeps its real monthly log returns minus a constant, so it ends at `final_ratio` x its t0 price."""
    months, horizon = _months(cfg), cfg["backtest"]["horizon_months"]
    prices = {}
    for name in cfg["data"]["etfs"]:
        price = panel.loc[months, name + PRICE_SUFFIX].to_numpy()
        drift = (np.log(price[-1] / price[0]) - np.log(final_ratio)) / horizon
        prices[name] = price * np.exp(-drift * np.arange(horizon + 1))
    return with_prices(panel, cfg, prices)


def crash(panel: pd.DataFrame, cfg: dict[str, Any], at_month: int, fall: float) -> pd.DataFrame:
    """Real prices until month `at_month` - 1, a fall of `fall` in month `at_month`, then flat."""
    months = _months(cfg)
    prices = {}
    for name in cfg["data"]["etfs"]:
        price = panel.loc[months, name + PRICE_SUFFIX].to_numpy().copy()
        price[at_month:] = price[at_month - 1] * (1 - fall)
        prices[name] = price
    return with_prices(panel, cfg, prices)


def scenarios(panel: pd.DataFrame, cfg: dict[str, Any]) -> dict[str, pd.DataFrame]:
    """Real data, ETFs at -50 % and -80 % in 10 years, and a 60 % crash in the month after the review
    before the first payment (month 37, nov-2019), with no recovery."""
    return {
        "real": panel,
        "etf_-50%": drift_down(panel, cfg, 0.5),
        "etf_-80%": drift_down(panel, cfg, 0.2),
        "crash_-60%": crash(panel, cfg, at_month=37, fall=0.60),
    }


PLANS = ["cdt_ladder", "ldi", "trend_ldi"]
METRICS = [
    "final_wealth_net_cop",
    "shortfall_months",
    "total_shortfall_cop",
    "annual_return",
    "annual_volatility",
    "max_drawdown",
]


def stress_summary(panel: pd.DataFrame, payment_schedule: pd.DataFrame, cfg: dict[str, Any]) -> pd.DataFrame:
    """One row per (scenario, plan) with the `summary` metrics of `METRICS`."""
    rows = []
    for scenario, stressed in scenarios(panel, cfg).items():
        for plan in PLANS:
            s = summary(run_backtest(stressed, payment_schedule, cfg, plan))
            rows.append({"scenario": scenario, "plan": plan, **{k: s[k] for k in METRICS}})
    return pd.DataFrame(rows)


def main() -> None:
    from uvr_loan.amortization import schedule
    from uvr_loan.config import RESULTS_DIR, load_assumptions
    from uvr_loan.data.cleaning import load_monthly_panel

    cfg = load_assumptions()
    table = stress_summary(load_monthly_panel(cfg), schedule(cfg["loan"]), cfg)
    RESULTS_DIR.mkdir(exist_ok=True)
    table.to_csv(RESULTS_DIR / "stress_summary.csv", index=False)
    pd.set_option("display.width", 200)
    print(table.to_string(index=False, float_format=lambda x: f"{x:,.4f}"))
    print(f"Written to {RESULTS_DIR}")


if __name__ == "__main__":
    main()

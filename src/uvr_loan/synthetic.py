"""Synthetic ETF scenarios: plans 2-4 when the ETF prices follow made-up paths.

Only the ETF prices change from t0 on; UVR, CDT rates, FIC returns and payments stay historical.
Each ETF follows, from its real price P_0 at t0 (t = m / 12 years):

    log P_m = log P_0 + drift_ea * t + amplitude * sin(2 pi m / period_months) + sigma_ea * W_m
              + log(1 - crash_fall) if m >= crash_month

with W a Brownian motion sampled monthly. The scenarios are in `synthetic_etfs` of the config. Every
scenario uses the same noise draws (one seed), so they differ only in their deterministic part; each
ETF has its own draws. `<name>_trend_ret` is updated with the new prices (`with_prices`), so the
trend filter of plan 4 sees them. `<name>_vol_ea` stays historical: it only changes the split between
the ETFs, not how much goes to them.

Run `python -m uvr_loan.synthetic` to write results/synthetic/: summary.csv, prices.csv and
<scenario>/<plan>.csv.
"""

from typing import Any

import numpy as np
import pandas as pd

from uvr_loan.backtest import PRICE_SUFFIX, run_backtest, summary
from uvr_loan.cashflows import month_to_period

TREND_SUFFIX = "_trend_ret"
PLANS = ["cdt_ladder", "ldi", "trend_ldi"]  # plan 1 is left out: it holds no ETF
METRICS = [
    "final_wealth_net_cop",
    "shortfall_months",
    "total_shortfall_cop",
    "annual_return",
    "annual_volatility",
    "max_drawdown",
]


def with_prices(panel: pd.DataFrame, cfg: dict[str, Any], prices: dict[str, np.ndarray]) -> pd.DataFrame:
    """Copy of the panel with the prices of months t0 .. t0 + horizon of each ETF in `prices` replaced,
    and its `<name>_trend_ret` updated with the new prices.

    With f_m = new price / real price (1 before t0), 1 + new trend_m = (1 + real trend_m) * f_m / f_{m-w},
    with w = `data.trend_window_months`.
    """
    bt = cfg["backtest"]
    months = [month_to_period(bt["t0"], m) for m in range(bt["horizon_months"] + 1)]
    new = panel.copy()
    for name, price in prices.items():
        column = name + PRICE_SUFFIX
        factor = pd.Series(1.0, index=panel.index)
        factor[months] = np.asarray(price) / panel.loc[months, column].to_numpy()
        new.loc[months, column] = price
        before = factor.shift(cfg["data"]["trend_window_months"]).fillna(1.0)
        new[name + TREND_SUFFIX] = (1 + panel[name + TREND_SUFFIX]) * factor / before - 1
    return new


def synthetic_path(
    p0: float,
    horizon: int,
    noise: np.ndarray,
    drift_ea: float,
    sigma_ea: float,
    amplitude: float = 0.0,
    period_months: float | None = None,
    crash_month: int | None = None,
    crash_fall: float = 0.0,
) -> np.ndarray:
    """Prices of months 0..horizon, starting at `p0`. `noise` holds the `horizon` standard normal
    draws of the monthly Brownian increments. Raises ValueError on a negative `sigma_ea`, a
    `crash_fall` outside [0, 1) or `noise` of the wrong length."""
    if sigma_ea < 0:
        raise ValueError(f"sigma_ea must not be negative, got {sigma_ea}")
    if not 0 <= crash_fall < 1:
        raise ValueError(f"crash_fall must be in [0, 1), got {crash_fall}")
    if len(noise) != horizon:
        raise ValueError(f"noise must have {horizon} draws, got {len(noise)}")
    months = np.arange(horizon + 1)
    brownian = np.concatenate([[0.0], np.cumsum(noise) * np.sqrt(1 / 12)])
    log_ratio = drift_ea * months / 12 + sigma_ea * brownian
    if period_months is not None:
        log_ratio += amplitude * np.sin(2 * np.pi * months / period_months)
    if crash_month is not None:
        log_ratio += np.where(months >= crash_month, np.log(1 - crash_fall), 0.0)
    return p0 * np.exp(log_ratio)


def synthetic_panels(panel: pd.DataFrame, cfg: dict[str, Any]) -> dict[str, pd.DataFrame]:
    """One copy of the panel per scenario of `synthetic_etfs`, with the ETF prices from t0 replaced.
    Raises ValueError if a scenario names an ETF that is not in `data.etfs`."""
    params, names = cfg["synthetic_etfs"], list(cfg["data"]["etfs"])
    bt = cfg["backtest"]
    horizon, t0 = bt["horizon_months"], pd.Period(bt["t0"], "M")
    noise = dict(
        zip(names, np.random.default_rng(params["seed"]).standard_normal((len(names), horizon)), strict=True)
    )
    panels = {}
    for scenario, etfs in params["scenarios"].items():
        unknown = set(etfs) - set(names)
        if unknown:
            raise ValueError(f"Scenario {scenario} names ETFs not in data.etfs: {', '.join(sorted(unknown))}")
        prices = {}
        for name, spec in etfs.items():
            spec = {"sigma_ea": params["sigma_ea"]} | spec
            prices[name] = synthetic_path(panel.loc[t0, name + PRICE_SUFFIX], horizon, noise[name], **spec)
        panels[scenario] = with_prices(panel, cfg, prices)
    return panels


def synthetic_summary(
    panels: dict[str, pd.DataFrame], payment_schedule: pd.DataFrame, cfg: dict[str, Any]
) -> pd.DataFrame:
    """One row per (scenario, plan) with the `summary` metrics of `METRICS`."""
    rows = []
    for scenario, panel in panels.items():
        for plan in PLANS:
            s = summary(run_backtest(panel, payment_schedule, cfg, plan))
            rows.append({"scenario": scenario, "plan": plan, **{k: s[k] for k in METRICS}})
    return pd.DataFrame(rows)


def prices_table(panels: dict[str, pd.DataFrame], cfg: dict[str, Any]) -> pd.DataFrame:
    """Long table with month, scenario and the price and trailing return of each ETF, months 0..horizon."""
    bt = cfg["backtest"]
    t0 = pd.Period(bt["t0"], "M")
    months = [t0 + m for m in range(bt["horizon_months"] + 1)]
    columns = [name + suffix for name in cfg["data"]["etfs"] for suffix in (PRICE_SUFFIX, TREND_SUFFIX)]
    frames = [
        panel.loc[months, columns].assign(month=range(len(months)), scenario=scenario)
        for scenario, panel in panels.items()
    ]
    return pd.concat(frames)[["month", "scenario", *columns]]


def main() -> None:
    import logging

    from uvr_loan.amortization import schedule
    from uvr_loan.config import SYNTHETIC_DIR, load_assumptions
    from uvr_loan.data.cleaning import load_monthly_panel

    # The data checks of the FIC index are reported by `python -m uvr_loan.data.cleaning`.
    logging.getLogger("uvr_loan.data.cleaning").setLevel(logging.ERROR)
    cfg = load_assumptions()
    payment_schedule = schedule(cfg["loan"])
    panels = synthetic_panels(load_monthly_panel(cfg), cfg)
    for scenario, panel in panels.items():
        (SYNTHETIC_DIR / scenario).mkdir(parents=True, exist_ok=True)
        for plan in PLANS:
            results = run_backtest(panel, payment_schedule, cfg, plan)
            results.to_csv(SYNTHETIC_DIR / scenario / f"{plan}.csv", index=False)
    prices_table(panels, cfg).to_csv(SYNTHETIC_DIR / "prices.csv", index=False)
    table = synthetic_summary(panels, payment_schedule, cfg)
    table.to_csv(SYNTHETIC_DIR / "summary.csv", index=False)
    pd.set_option("display.width", 200)
    print(table.to_string(index=False, float_format=lambda x: f"{x:,.4f}"))
    print(f"Written to {SYNTHETIC_DIR}")


if __name__ == "__main__":
    main()

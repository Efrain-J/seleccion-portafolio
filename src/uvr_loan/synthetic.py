"""Synthetic ETF scenarios: plans 2-4 when the ETF prices follow made-up paths, many paths per scenario.

Only the ETF prices change from t0 on; UVR, CDT rates, FIC returns and payments stay historical.
Each ETF follows, from its real price P_0 at t0 (t = m / 12 years):

    log P_m = log P_0 + drift_ea * t + amplitude * sin(2 pi m / period_months) + sigma_ea * W_m
              + log(1 - crash_fall) if m >= crash_month

with W a Brownian motion sampled monthly. The scenarios are in `synthetic_etfs` of the config. There
are `n_paths` paths drawn from one `seed`; path j uses the same noise draws in every scenario, so the
scenarios differ only in their deterministic part, and each ETF has its own draws. `with_prices`
also updates `<name>_vol_ea`, so the split between the ETFs follows the new volatility.

Plan 2 holds no ETF, so it is run once. Plans 3 and 4 are run on every path (`monte_carlo`, in
parallel) and summarized as distributions (`distribution_summary`).

Run `python -m uvr_loan.synthetic` to write results/synthetic/: summary.csv, fan.csv (monthly
percentiles of the net wealth) and, for the example path 0, prices.csv and <scenario>/<plan>.csv.
"""

import os
from concurrent.futures import ProcessPoolExecutor
from typing import Any

import numpy as np
import pandas as pd

from uvr_loan.backtest import PRICE_SUFFIX, run_backtest, summary
from uvr_loan.cashflows import month_to_period

VOL_SUFFIX = "_vol_ea"
PLANS = ["cdt_ladder", "ldi", "ratchet_ldi"]  # plan 1 is left out: it holds no ETF
ETF_PLANS = ("ldi", "ratchet_ldi")  # the plans that depend on the ETF prices
METRICS = [
    "final_wealth_net_cop",
    "shortfall_months",
    "total_shortfall_cop",
    "annual_return",
    "annual_volatility",
    "max_drawdown",
]
PERCENTILES = (10, 50, 90)


def with_prices(panel: pd.DataFrame, cfg: dict[str, Any], prices: dict[str, np.ndarray]) -> pd.DataFrame:
    """Copy of the panel with the prices of months t0 .. t0 + horizon of each ETF in `prices` replaced,
    and its `<name>_vol_ea` updated with the new prices.

    Volatility: the panel does not hold the 36 months before t0, so the months of the window before t0
    keep the volatility of t0, sigma_0. With w = `data.vol_window_months`, n = min(m, w) new monthly
    returns in the window and their annualized sample variance s_m^2 (sigma_0^2 if n < 2):
    sigma_m^2 = ((w - n) * sigma_0^2 + n * s_m^2) / w. Month t0 keeps sigma_0.
    """
    bt, data = cfg["backtest"], cfg["data"]
    months = [month_to_period(bt["t0"], m) for m in range(bt["horizon_months"] + 1)]
    new = panel.copy()
    for name, price in prices.items():
        column, price = name + PRICE_SUFFIX, np.asarray(price, dtype=float)
        new.loc[months, column] = price
        new.loc[months[1:], name + VOL_SUFFIX] = _pooled_volatility(
            price, panel.loc[months[0], name + VOL_SUFFIX], data["vol_window_months"]
        )
    return new


def _pooled_volatility(price: np.ndarray, sigma_0: float, window: int) -> np.ndarray:
    """Annual volatility of months 1..horizon of `price` (see `with_prices`)."""
    returns = pd.Series(price[1:] / price[:-1] - 1)
    n = np.minimum(np.arange(1, len(returns) + 1), window)
    sample = (returns.rolling(window, min_periods=2).var() * 12).fillna(sigma_0**2).to_numpy()
    return np.sqrt(((window - n) * sigma_0**2 + n * sample) / window)


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


def draw_noise(cfg: dict[str, Any]) -> np.ndarray:
    """Standard normal draws of shape (n_paths, number of ETFs, horizon), from `synthetic_etfs.seed`."""
    params = cfg["synthetic_etfs"]
    shape = (params["n_paths"], len(cfg["data"]["etfs"]), cfg["backtest"]["horizon_months"])
    return np.random.default_rng(params["seed"]).standard_normal(shape)


def _scenario_specs(cfg: dict[str, Any]) -> dict[str, dict[str, dict[str, Any]]]:
    """Path parameters of each ETF in each scenario, with the default `sigma_ea` filled in.
    Raises ValueError if a scenario names an ETF that is not in `data.etfs`."""
    params, names = cfg["synthetic_etfs"], set(cfg["data"]["etfs"])
    specs = {}
    for scenario, etfs in params["scenarios"].items():
        unknown = set(etfs) - names
        if unknown:
            raise ValueError(f"Scenario {scenario} names ETFs not in data.etfs: {', '.join(sorted(unknown))}")
        specs[scenario] = {name: {"sigma_ea": params["sigma_ea"]} | spec for name, spec in etfs.items()}
    return specs


def synthetic_panels(
    panel: pd.DataFrame, cfg: dict[str, Any], path: int = 0, noise: np.ndarray | None = None
) -> dict[str, pd.DataFrame]:
    """One copy of the panel per scenario, with the ETF prices of path `path` from t0 on.
    `noise` is `draw_noise(cfg)`; pass it when building many paths so it is drawn once."""
    noise = draw_noise(cfg) if noise is None else noise
    names = list(cfg["data"]["etfs"])
    bt = cfg["backtest"]
    horizon, t0 = bt["horizon_months"], pd.Period(bt["t0"], "M")
    panels = {}
    for scenario, etfs in _scenario_specs(cfg).items():
        prices = {
            name: synthetic_path(
                panel.loc[t0, name + PRICE_SUFFIX], horizon, noise[path, names.index(name)], **spec
            )
            for name, spec in etfs.items()
        }
        panels[scenario] = with_prices(panel, cfg, prices)
    return panels


def median_growth(cfg: dict[str, Any]) -> dict[str, float]:
    """Growth of the ETFs over the horizon without noise (the median path), averaged over the ETFs of
    each scenario: it tells whether the scenario gives the ETFs a positive premium."""
    horizon = cfg["backtest"]["horizon_months"]
    zero = np.zeros(horizon)
    return {
        scenario: float(
            np.mean([synthetic_path(1.0, horizon, zero, **spec)[-1] - 1 for spec in etfs.values()])
        )
        for scenario, etfs in _scenario_specs(cfg).items()
    }


# Monte Carlo. The workers are separate processes (Windows starts them anew), so the functions they run
# are at module level and the inputs are sent once per worker through `_init_worker`.
_WORKER: dict[str, Any] = {}


def _init_worker(panel, payment_schedule, cfg, noise, plans) -> None:
    _WORKER.update(panel=panel, payment_schedule=payment_schedule, cfg=cfg, noise=noise, plans=plans)


def _run_paths(paths: list[int]) -> tuple[list[dict[str, Any]], dict[tuple[str, str], list[np.ndarray]]]:
    """Run the plans on every scenario of each path: the metrics rows and the monthly net wealth."""
    w = _WORKER
    rows, wealth = [], {}
    for path in paths:
        for scenario, panel in synthetic_panels(w["panel"], w["cfg"], path, w["noise"]).items():
            for plan in w["plans"]:
                results = run_backtest(panel, w["payment_schedule"], w["cfg"], plan)
                metrics = summary(results)
                rows.append(
                    {"scenario": scenario, "path": path, "plan": plan, **{k: metrics[k] for k in METRICS}}
                )
                wealth.setdefault((scenario, plan), []).append(results["wealth_net_cop"].to_numpy())
    return rows, wealth


def monte_carlo(
    panel: pd.DataFrame,
    payment_schedule: pd.DataFrame,
    cfg: dict[str, Any],
    plans: tuple[str, ...] = ETF_PLANS,
    workers: int | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Run `plans` on the `n_paths` paths of every scenario.

    Returns (paths, fan): one row per (scenario, path, plan) with `METRICS`, and the 10th, 50th and 90th
    percentiles of the net wealth per (scenario, plan, month). `workers=1` runs in this process; more
    workers run blocks of paths in parallel (each worker keeps its own ladder LP cache across its paths).
    """
    noise = draw_noise(cfg)
    n_paths = cfg["synthetic_etfs"]["n_paths"]
    workers = workers or os.cpu_count() or 1
    blocks = [list(b) for b in np.array_split(np.arange(n_paths), min(n_paths, workers * 4)) if len(b)]
    blocks = [[int(path) for path in block] for block in blocks]
    args = (panel, payment_schedule, cfg, noise, plans)
    if workers == 1:
        _init_worker(*args)
        outputs = [_run_paths(block) for block in blocks]
    else:
        with ProcessPoolExecutor(max_workers=workers, initializer=_init_worker, initargs=args) as pool:
            outputs = list(pool.map(_run_paths, blocks))

    rows = [row for block_rows, _ in outputs for row in block_rows]
    paths = pd.DataFrame(rows).sort_values(["scenario", "path", "plan"], ignore_index=True)
    wealth: dict[tuple[str, str], list[np.ndarray]] = {}
    for _, block_wealth in outputs:  # the blocks come back in order, so the paths stay in order
        for key, arrays in block_wealth.items():
            wealth.setdefault(key, []).extend(arrays)
    fan = pd.concat(
        [_fan_rows(scenario, plan, np.vstack(arrays)) for (scenario, plan), arrays in sorted(wealth.items())],
        ignore_index=True,
    )
    return paths, fan


def _fan_rows(scenario: str, plan: str, wealth: np.ndarray) -> pd.DataFrame:
    """Percentiles over the paths (rows of `wealth`) of each month (columns)."""
    p10, p50, p90 = np.percentile(wealth, PERCENTILES, axis=0)
    return pd.DataFrame(
        {
            "scenario": scenario,
            "plan": plan,
            "month": np.arange(wealth.shape[1]),
            "p10": p10,
            "p50": p50,
            "p90": p90,
        }
    )


def distribution_summary(
    paths: pd.DataFrame, plan2: dict[str, float], growth: dict[str, float]
) -> pd.DataFrame:
    """One row per (scenario, plan) from the `monte_carlo` paths.

    Columns: `etf_median_growth` (from `median_growth`), the mean and percentiles of the final net
    wealth, the mean and 90th percentile of the max drawdown, `shortfall_share` (paths with at least one
    month of shortfall) and `beats_plan3` (paths where the plan ends with more net wealth than plan 3 on
    the same path; NaN for plan 3). `plan2` is the `summary` of plan 2, which does not depend on the
    ETFs: it gets one row per scenario with its single value.
    """
    plan2_rows = paths[paths["plan"] == "ldi"][["scenario", "path"]].assign(
        plan="cdt_ladder",
        **{k: plan2[k] for k in ("final_wealth_net_cop", "max_drawdown", "shortfall_months")},
    )
    data = pd.concat([plan2_rows, paths], ignore_index=True)
    plan3 = paths[paths["plan"] == "ldi"].set_index(["scenario", "path"])["final_wealth_net_cop"]
    rows = []
    for (scenario, plan), group in data.groupby(["scenario", "plan"], sort=False):
        wealth, drawdown = group["final_wealth_net_cop"], group["max_drawdown"]
        reference = plan3.loc[scenario].reindex(group["path"]).to_numpy()
        rows.append(
            {
                "scenario": scenario,
                "plan": plan,
                "etf_median_growth": growth[scenario],
                "wealth_mean": wealth.mean(),
                **{f"wealth_p{q}": np.percentile(wealth, q) for q in PERCENTILES},
                "drawdown_mean": drawdown.mean(),
                "drawdown_p90": np.percentile(drawdown, 90),
                "shortfall_share": (group["shortfall_months"] > 0).mean(),
                "beats_plan3": np.nan if plan == "ldi" else float(np.mean(wealth.to_numpy() > reference)),
            }
        )
    order = {plan: i for i, plan in enumerate(PLANS)}
    table = pd.DataFrame(rows)
    scenarios = list(dict.fromkeys(paths["scenario"]))
    return table.sort_values(
        ["scenario", "plan"],
        key=lambda c: c.map(scenarios.index) if c.name == "scenario" else c.map(order),
        ignore_index=True,
    )


def prices_table(panels: dict[str, pd.DataFrame], cfg: dict[str, Any]) -> pd.DataFrame:
    """Long table with month, scenario and the price of each ETF, months 0..horizon."""
    bt = cfg["backtest"]
    t0 = pd.Period(bt["t0"], "M")
    months = [t0 + m for m in range(bt["horizon_months"] + 1)]
    columns = [name + PRICE_SUFFIX for name in cfg["data"]["etfs"]]
    frames = [
        panel.loc[months, columns].assign(month=range(len(months)), scenario=scenario)
        for scenario, panel in panels.items()
    ]
    return pd.concat(frames)[["month", "scenario", *columns]]


def main() -> None:
    import logging
    import time

    from uvr_loan.amortization import schedule
    from uvr_loan.config import SYNTHETIC_DIR, load_assumptions
    from uvr_loan.data.cleaning import load_monthly_panel

    # The data checks of the FIC index are reported by `python -m uvr_loan.data.cleaning`.
    logging.getLogger("uvr_loan.data.cleaning").setLevel(logging.ERROR)
    start = time.perf_counter()
    cfg = load_assumptions()
    panel, payment_schedule = load_monthly_panel(cfg), schedule(cfg["loan"])

    # The example path 0, month by month, for the notebook.
    example = synthetic_panels(panel, cfg, path=0)
    for scenario, scenario_panel in example.items():
        (SYNTHETIC_DIR / scenario).mkdir(parents=True, exist_ok=True)
        for plan in PLANS:
            results = run_backtest(scenario_panel, payment_schedule, cfg, plan)
            results.to_csv(SYNTHETIC_DIR / scenario / f"{plan}.csv", index=False)
    prices_table(example, cfg).to_csv(SYNTHETIC_DIR / "prices.csv", index=False)

    plan2 = run_backtest(panel, payment_schedule, cfg, "cdt_ladder")  # the same in every scenario and path
    paths, fan = monte_carlo(panel, payment_schedule, cfg)
    plan2_fan = [
        pd.DataFrame({"scenario": s, "plan": "cdt_ladder", "month": plan2["month"]}).assign(
            **{f"p{q}": plan2["wealth_net_cop"] for q in PERCENTILES}
        )
        for s in cfg["synthetic_etfs"]["scenarios"]
    ]
    pd.concat([*plan2_fan, fan], ignore_index=True).to_csv(SYNTHETIC_DIR / "fan.csv", index=False)
    table = distribution_summary(paths, summary(plan2), median_growth(cfg))
    table.to_csv(SYNTHETIC_DIR / "summary.csv", index=False)

    pd.set_option("display.width", 250)
    shown = table.copy()
    money = [c for c in shown.columns if c.startswith("wealth_")]
    shown[money] = shown[money] / 1e6
    print(shown.to_string(index=False, float_format=lambda x: f"{x:,.3f}"))
    n_paths = cfg["synthetic_etfs"]["n_paths"]
    print(
        f"{n_paths} paths, wealth in millions of COP, {time.perf_counter() - start:.0f} s. Written to {SYNTHETIC_DIR}"
    )


if __name__ == "__main__":
    main()

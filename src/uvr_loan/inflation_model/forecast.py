"""Forecast of the inflation of the next `horizon_months` months (p05, median and p99.5) for every month-end.

For each origin month, using only what is known at its close:

1. The Hull-White simulation of the implied inflation (COP against UVR curves) gives a sample of the inflation of the
   next months.
2. That sample is corrected with what the model got wrong in the past: its mean error (bias) once the seasonality is
   removed, the seasonal factor of the target months and an extra noise that completes the observed dispersion.
   Only origins whose target is already realized enter the errors (`origin <= month - lag`).

The result is the file `inflation_scenarios.forecast_file`, read by `uvr_loan.inflation.forecast_base`.
Run `python -m uvr_loan.inflation_model.forecast [output.csv]` to write it.
"""

import sys
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from uvr_loan.config import ROOT, load_assumptions
from uvr_loan.data.sources import load_uvr
from uvr_loan.inflation_model.cpi import (
    UVR_LAG_MONTHS,
    cpi_target,
    monthly_cpi,
    seasonal_adjustment,
    seasonal_factors,
)
from uvr_loan.inflation_model.hull_white import simulate_hull_white
from uvr_loan.inflation_model.nelson_siegel import implied_inflation, load_betas, rolling_std

STEPS_PER_YEAR = 12  # monthly steps: the CPI is monthly
SIMULATED_YEARS = 1  # enough to cover the forecast horizon
LOW_PERCENTILE = 0.05  # the `p05_ea` column
HIGH_PERCENTILE = 0.995  # the `p995_ea` column
HISTORY_COLUMNS = ["realised", "breakeven_1y", "hw_mean", "seasonal"]
OUTPUT_COLUMNS = ["p05_ea", "median_ea", "p995_ea", "mean_ea", "breakeven_1y_ea"]


def sample_at_horizon(simulation: dict[str, Any], horizon_months: int) -> pd.Series:
    """Simulated spot rate (one value per path) at the step closest to `horizon_months`."""
    column = int(np.argmin(np.abs(simulation["time_axis"] - horizon_months / 12)))
    return simulation["spot_rates"].iloc[:, column]


def simulate_origin(
    betas: pd.DataFrame, cutoff: pd.Timestamp, cfg: dict[str, Any]
) -> tuple[np.ndarray, float]:
    """Sample of the inflation of the next months and the 1-year implied inflation, with the betas up to `cutoff`."""
    model = cfg["inflation_model"]
    known = betas[betas["date"] <= pd.Timestamp(cutoff)]
    tenors = np.arange(1, model["tenors"] + 1)
    implied = implied_inflation(known, tenors)
    sigma = rolling_std(implied, model["vol_window_days"]).quantile(model["vol_percentile"])
    spot = implied.iloc[-1]
    simulation = simulate_hull_white(
        model["kappa_switch_years"],
        tuple(model["kappas"]),
        tenors,
        sigma,
        spot,
        STEPS_PER_YEAR,
        SIMULATED_YEARS,
        model["n_paths"],
        model["seed"],
    )
    return sample_at_horizon(simulation, model["horizon_months"]).to_numpy(), float(spot.iloc[0])


def build_history(
    betas: pd.DataFrame, uvr: pd.Series, cfg: dict[str, Any], origins: list[pd.Period]
) -> tuple[pd.DataFrame, dict[pd.Period, np.ndarray]]:
    """One row per origin (columns `HISTORY_COLUMNS`) and the simulated sample of each origin.

    `realised` is the realized inflation of the target months, NaN while the UVR does not reach them. The table also holds
    the future of every origin, so a reader must filter it (see `corrected_distribution`). `seasonal` is the factor known
    at that origin: it must not be recomputed afterwards.
    """
    horizon = cfg["inflation_model"]["horizon_months"]
    cpi = monthly_cpi(uvr)
    rows, samples = {}, {}
    for origin in origins:
        month_end = origin.to_timestamp(how="end").normalize()
        sample, breakeven = simulate_origin(betas, month_end, cfg)
        factors = seasonal_factors(cpi, until=origin - UVR_LAG_MONTHS)
        try:
            realised = cpi_target(uvr, month_end, horizon)
        except ValueError:  # the target is not realized yet: the row only serves to forecast
            realised = np.nan
        rows[origin] = {
            "realised": realised,
            "breakeven_1y": breakeven,
            "hw_mean": float(sample.mean()),
            "seasonal": seasonal_adjustment(factors, origin, horizon),
        }
        samples[origin] = sample
    return pd.DataFrame.from_dict(rows, orient="index", columns=HISTORY_COLUMNS), samples


def corrected_distribution(
    history: pd.DataFrame, sample: np.ndarray, origin: pd.Period, cfg: dict[str, Any]
) -> np.ndarray:
    """Hull-White sample of `origin` plus the mean past error, the seasonal factor and the missing dispersion.

    The error of a past origin j is `realised - hw_mean - seasonal`. Only the origins j <= origin - lag are used (lag =
    horizon + UVR lag): they are the ones whose target is known at `origin`; the rest of the table is the future and
    is never read, which is also what excludes the NaN of unrealized targets. The extra noise completes the standard
    deviation of those errors: `std(errors, ddof=1)` against `var(sample)` (ddof=0), as in the original model.
    """
    model = cfg["inflation_model"]
    lag = model["horizon_months"] + UVR_LAG_MONTHS
    past = history[history.index <= origin - lag]
    if len(past) < model["min_history"]:
        raise ValueError(
            f"Not enough history at {origin}: {len(past)} realized errors < {model['min_history']}"
        )
    errors = past["realised"] - past["hw_mean"] - past["seasonal"]
    extra_std = np.sqrt(max(errors.std(ddof=1) ** 2 - np.var(sample), 0.0))
    noise = np.random.default_rng(model["seed"]).normal(0.0, extra_std, len(sample))
    return np.asarray(sample) + errors.mean() + history.loc[origin, "seasonal"] + noise


def generate_forecasts(
    betas: pd.DataFrame, uvr: pd.Series, cfg: dict[str, Any], origins: list[pd.Period] | None = None
) -> pd.DataFrame:
    """Forecast of every month from `first_forecast` on (index `month`), in effective annual rates (decimal).

    By default the origins go from `first_origin` to the last month of the betas.
    """
    model = cfg["inflation_model"]
    if origins is None:
        last = betas["date"].max().to_period("M")
        origins = list(pd.period_range(model["first_origin"], last, freq="M"))
    first_forecast = pd.Period(model["first_forecast"], "M")
    history, samples = build_history(betas, uvr, cfg, origins)
    rows = {}
    for origin in origins:
        if origin < first_forecast:
            continue
        sample = corrected_distribution(history, samples[origin], origin, cfg)
        rows[str(origin)] = {
            "p05_ea": np.expm1(np.quantile(sample, LOW_PERCENTILE)),
            "median_ea": np.expm1(np.median(sample)),
            "p995_ea": np.expm1(np.quantile(sample, HIGH_PERCENTILE)),
            "mean_ea": np.expm1(sample.mean()),
            "breakeven_1y_ea": history.loc[origin, "breakeven_1y"],
        }
    return pd.DataFrame.from_dict(rows, orient="index", columns=OUTPUT_COLUMNS).rename_axis("month")


def save_forecasts(forecasts: pd.DataFrame, path: Path) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    forecasts.to_csv(path, sep=";")


if __name__ == "__main__":
    cfg = load_assumptions()
    output = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / cfg["inflation_scenarios"]["forecast_file"]
    forecasts = generate_forecasts(load_betas(cfg), load_uvr(cfg), cfg)
    save_forecasts(forecasts, output)
    print(forecasts.iloc[::12].to_string(float_format=lambda x: f"{x:.4f}"))
    print(f"{len(forecasts)} months written to {output}")

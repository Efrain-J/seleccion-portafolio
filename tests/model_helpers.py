"""Synthetic config, betas and UVR shared by the inflation model tests."""

from typing import Any

import numpy as np
import pandas as pd

BETA_COLUMNS = [f"{b}_{c}" for c in ("cop", "uvr") for b in ("beta0", "beta1", "beta2", "tau")]

# Monthly CPI pattern (log, before scaling): high in January, low in the second half of the year.
SEASONAL_PATTERN = np.array(
    [0.012, 0.006, 0.004, 0.003, 0.002, 0.002, 0.001, 0.0, 0.001, 0.001, 0.002, 0.004]
)


def make_model_cfg(**overrides: Any) -> dict[str, Any]:
    """Config with the sections of the inflation model; small sizes so the tests run fast."""
    model = {
        "betas_file": "data/raw/betas_historicos.csv",
        "betas_start": "2010-01-01",
        "tenors": 10,
        "vol_window_days": 60,
        "vol_percentile": 0.995,
        "kappas": [0.11, 0.13],
        "kappa_switch_years": 5,
        "n_paths": 200,
        "seed": 123456,
        "horizon_months": 6,
        "min_history": 12,
        "first_origin": "2016-01",
        "first_forecast": "2017-08",
    }
    return {
        "inflation_model": model | overrides,
        "inflation_scenarios": {"forecast_file": "data/forecasts/hw_inflation_forecasts.csv"},
    }


def synthetic_betas(start: str = "2015-01-01", end: str = "2018-01-31") -> pd.DataFrame:
    """Daily betas (percent) with the English column names that `load_betas` returns."""
    dates = pd.date_range(start, end, freq="D")
    n = len(dates)
    return pd.DataFrame(
        {
            "date": dates,
            "beta0_cop": 8.0 + 0.5 * np.sin(np.arange(n) / 30),
            "beta1_cop": -2.0,
            "beta2_cop": 1.0,
            "tau_cop": 2.0,
            "beta0_uvr": 5.0 + 0.3 * np.sin(np.arange(n) / 40),
            "beta1_uvr": -1.0,
            "beta2_uvr": 0.5,
            "tau_uvr": 2.0,
        }
    )


def synthetic_uvr(start: str = "2008-01-01", end: str = "2018-03-31") -> pd.Series:
    """Daily UVR growing ~6 % a year with a mild seasonal ripple."""
    dates = pd.date_range(start, end, freq="D")
    years = (dates - dates[0]).days / 365.0
    return pd.Series(100 * np.exp(0.06 * years + 0.002 * np.sin(2 * np.pi * years)), index=dates)


def uvr_from_cpi(cpi: pd.Series) -> pd.Series:
    """UVR observed on the 15th of each month such that ln(u[m] / u[m-1]) = CPI(m - 2)."""
    first = cpi.index[0] + 1
    level = 100 * np.exp(np.concatenate([[0.0], np.cumsum(cpi.to_numpy())]))
    months = pd.period_range(first, periods=len(level), freq="M")
    return pd.Series(level, index=[m.to_timestamp() + pd.Timedelta(days=14) for m in months])

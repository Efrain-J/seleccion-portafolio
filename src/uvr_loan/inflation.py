"""Inflation scenarios and projected UVR path.

`scenarios` is the interface for the inflation model: it returns the annual
inflation of each planning scenario (low, base, high) at a decision date, using only
what is known up to that date. There are two sources (`inflation_scenarios.source`):
the inflation of the last `base_lookback_months` months of the UVR plus fixed shocks
(the default, a provisional model), and the forecast file written by
`uvr_loan.inflation_model`, where each scenario is a column of the file.
"""

from functools import cache
from typing import Any

import numpy as np
import pandas as pd

from uvr_loan.config import ROOT


def trailing_inflation(uvr: pd.Series, months: int) -> float:
    """Annualized inflation of the last `months` months of `uvr` (the series ends at the decision date)."""
    if len(uvr) <= months:
        raise ValueError(f"Need more than {months} months of UVR history, got {len(uvr)}")
    return (uvr.iloc[-1] / uvr.iloc[-1 - months]) ** (12 / months) - 1


@cache
def _load_forecasts(path: str) -> pd.DataFrame:
    return pd.read_csv(path, sep=";", index_col="month")


def forecast_scenarios(cfg: dict[str, Any], uvr_history: pd.Series) -> dict[str, float]:
    """Annual inflation (decimal) of the low, base and high scenarios, read from the forecast file.

    The file (`inflation_scenarios.forecast_file`, relative to the project root) has one row per month with the
    statistics of the forecast distribution, made with information up to the close of that month. The row is the
    decision month (the last index of `uvr_history`) and `forecast_columns` says which column is each scenario
    (by default p05, median and p99.5).
    """
    s = cfg["inflation_scenarios"]
    table = _load_forecasts(str(ROOT / s["forecast_file"]))
    month = str(uvr_history.index[-1])
    unknown = sorted(set(s["forecast_columns"].values()) - set(table.columns))
    if unknown:
        raise ValueError(f"Columns {unknown} are not in the forecast file, which has {list(table.columns)}")
    if month not in table.index:
        raise ValueError(f"The forecast file has no row for month {month}")
    return {name: float(table.loc[month, column]) for name, column in s["forecast_columns"].items()}


def scenarios(cfg: dict[str, Any], uvr_history: pd.Series) -> dict[str, float]:
    """Annual inflation (decimal) for the low, base and high scenarios, from information up to the decision date.

    `inflation_scenarios.source` is `trailing` (the base is the inflation of the last months of the UVR, and high and
    low add the shocks `high_shock_pp` and `low_shock_pp`) or `forecast` (the three scenarios come from the
    forecast distribution, see `forecast_scenarios`; no shocks).
    """
    s = cfg["inflation_scenarios"]
    if s.get("source", "trailing") == "forecast":
        return forecast_scenarios(cfg, uvr_history)
    base = trailing_inflation(uvr_history, s["base_lookback_months"])
    return {
        "base": base,
        "high": base + s["high_shock_pp"] / 100,
        "low": base + s["low_shock_pp"] / 100,
    }


def project_uvr(uvr_tau: float, annual_inflation: float, months: int) -> np.ndarray:
    """Projected UVR for months tau+1 .. tau+months, growing at constant monthly inflation."""
    monthly = (1 + annual_inflation) ** (1 / 12) - 1
    return uvr_tau * (1 + monthly) ** np.arange(1, months + 1)

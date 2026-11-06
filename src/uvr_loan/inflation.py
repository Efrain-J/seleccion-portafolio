"""Inflation scenarios and projected UVR path.

`scenarios` is the interface for the inflation model: it returns the annual
inflation of each planning scenario at a decision date, using only the UVR known
up to that date. For now the base is the inflation of the last
`base_lookback_months` months; the real model must keep the same signature.
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


def forecast_base(cfg: dict[str, Any], uvr_history: pd.Series) -> float:
    """Base annual inflation (decimal) from the forecast file, for the decision month (the last index of `uvr_history`).

    The file (`inflation_scenarios.forecast_file`, relative to the project root) has one row per month
    with the statistics of the forecast distribution; `forecast_stat` picks the column (median_ea, p995_ea).
    Every row was computed with information up to the close of its month.
    """
    s = cfg["inflation_scenarios"]
    table = _load_forecasts(str(ROOT / s["forecast_file"]))
    stat, month = s["forecast_stat"], str(uvr_history.index[-1])
    if stat not in table.columns:
        raise ValueError(
            f"forecast_stat {stat!r} is not a column of the forecast file: {list(table.columns)}"
        )
    if month not in table.index:
        raise ValueError(f"The forecast file has no row for month {month}")
    return float(table.loc[month, stat])


def scenarios(cfg: dict[str, Any], uvr_history: pd.Series) -> dict[str, float]:
    """Annual inflation (decimal) for the base, high and low scenarios, from the UVR up to the decision date.

    The base is the trailing inflation, or the forecast of the decision month if
    `inflation_scenarios.source` is `forecast`; high and low add the same shocks in both cases.
    """
    s = cfg["inflation_scenarios"]
    if s.get("source", "trailing") == "forecast":
        base = forecast_base(cfg, uvr_history)
    else:
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

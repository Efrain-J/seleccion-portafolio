"""Inflation scenarios and projected UVR path.

`scenarios` is the interface for the inflation model: it returns the annual
inflation of each planning scenario at a decision date, using only the UVR known
up to that date. For now the base is the inflation of the last
`base_lookback_months` months; the real model must keep the same signature.
"""

from typing import Any

import numpy as np
import pandas as pd


def trailing_inflation(uvr: pd.Series, months: int) -> float:
    """Annualized inflation of the last `months` months of `uvr` (the series ends at the decision date)."""
    if len(uvr) <= months:
        raise ValueError(f"Need more than {months} months of UVR history, got {len(uvr)}")
    return (uvr.iloc[-1] / uvr.iloc[-1 - months]) ** (12 / months) - 1


def scenarios(cfg: dict[str, Any], uvr_history: pd.Series) -> dict[str, float]:
    """Annual inflation (decimal) for the base, high and low scenarios, from the UVR up to the decision date."""
    s = cfg["inflation_scenarios"]
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

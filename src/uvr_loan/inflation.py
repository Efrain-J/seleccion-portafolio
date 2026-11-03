"""Inflation scenarios and projected UVR path.

`scenarios` is the interface for the inflation model: it returns the annual
inflation of each planning scenario at a decision date. For now the base comes
from config/assumptions.yaml; the real model must keep the same signature.
"""

from typing import Any

import numpy as np
import pandas as pd


def scenarios(cfg: dict[str, Any], tau: pd.Period | None = None) -> dict[str, float]:
    """Annual inflation (decimal) for the base, high and low scenarios at decision date `tau`."""
    s = cfg["inflation_scenarios"]
    base = s["base_annual"]
    return {
        "base": base,
        "high": base + s["high_shock_pp"] / 100,
        "low": base + s["low_shock_pp"] / 100,
    }


def project_uvr(uvr_tau: float, annual_inflation: float, months: int) -> np.ndarray:
    """Projected UVR for months tau+1 .. tau+months, growing at constant monthly inflation."""
    monthly = (1 + annual_inflation) ** (1 / 12) - 1
    return uvr_tau * (1 + monthly) ** np.arange(1, months + 1)

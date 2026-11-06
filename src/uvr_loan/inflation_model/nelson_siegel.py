"""Nelson-Siegel betas to rates by node, implied inflation and its rolling volatility.

The betas are the daily series of the Banco de la República (percent), downloaded by hand: see
`data/SOURCES.md`. The implied inflation (breakeven) of a node is (1 + COP) / (1 + UVR) - 1.
"""

from typing import Any

import numpy as np
import pandas as pd

from uvr_loan.config import ROOT

CURVES = ("cop", "uvr")
PARAMETERS = ("beta0", "beta1", "beta2", "tau")
BETA_COLUMNS = [f"{parameter}_{curve}" for curve in CURVES for parameter in PARAMETERS]
# Header of the file as the Banco publishes it -> column of the betas table.
FILE_COLUMNS = {
    "Fecha": "date",
    "B0_COP": "beta0_cop",
    "B1_COP": "beta1_cop",
    "B2_COP": "beta2_cop",
    "TAO_COP": "tau_cop",
    "B0_UVR": "beta0_uvr",
    "B1_UVR": "beta1_uvr",
    "B2_UVR": "beta2_uvr",
    "TAO_UVR": "tau_uvr",
}


def load_betas(cfg: dict[str, Any]) -> pd.DataFrame:
    """Daily betas (percent) from `inflation_model.betas_file`, from `betas_start` on, without incomplete rows.

    Columns: `date` and `<beta0|beta1|beta2|tau>_<cop|uvr>`. The COP betas are empty in the first years of the
    file, so the rows before the COP curve exists are dropped.
    """
    model = cfg["inflation_model"]
    path = ROOT / model["betas_file"]
    if not path.exists():
        raise FileNotFoundError(
            f"The betas file {path} does not exist. It is downloaded by hand from the Banco de la República "
            "(its portal blocks automated downloads); see data/SOURCES.md."
        )
    raw = pd.read_csv(path, sep=";")
    missing = sorted(set(FILE_COLUMNS) - set(raw.columns))
    if missing:
        raise ValueError(f"Missing columns in {path.name}: {missing}")
    betas = raw[list(FILE_COLUMNS)].rename(columns=FILE_COLUMNS)
    betas["date"] = pd.to_datetime(betas["date"])
    betas = betas[betas["date"] >= pd.Timestamp(model["betas_start"])]
    return betas.dropna(subset=BETA_COLUMNS).sort_values("date").reset_index(drop=True)


def nelson_siegel_nodes(betas: pd.DataFrame, tenors: np.ndarray, curve: str) -> pd.DataFrame:
    """Rate (decimal) of the `curve` ('cop' or 'uvr') at each tenor in years: one row per date, one column per tenor."""
    beta0, beta1, beta2, tau = (betas[f"{p}_{curve}"].to_numpy()[:, None] for p in PARAMETERS)
    ratio = tenors / tau  # (dates, 1) against (tenors,) broadcasts to (dates, tenors)
    loading1 = (1 - np.exp(-ratio)) / ratio
    loading2 = loading1 - np.exp(-ratio)
    rates = (beta0 + beta1 * loading1 + beta2 * loading2) / 100
    return pd.DataFrame(rates, index=pd.DatetimeIndex(betas["date"]), columns=tenors)


def implied_inflation(betas: pd.DataFrame, tenors: np.ndarray) -> pd.DataFrame:
    """Implied inflation of each node: (1 + COP) / (1 + UVR) - 1."""
    cop = nelson_siegel_nodes(betas, tenors, "cop")
    uvr = nelson_siegel_nodes(betas, tenors, "uvr")
    return (1 + cop) / (1 + uvr) - 1


def rolling_std(levels: pd.DataFrame, window: int) -> pd.DataFrame:
    """Sample standard deviation of each column over a rolling window of observations (incomplete windows dropped)."""
    return levels.rolling(window=window).std(ddof=1).dropna()

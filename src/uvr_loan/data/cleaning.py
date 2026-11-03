"""Monthly data panel (end of month) built from the raw series.

Run `python -m uvr_loan.data.cleaning` to write data/processed/monthly_panel.csv.
"""

from collections.abc import Iterable
from typing import Any

import pandas as pd

from uvr_loan.config import ROOT, load_assumptions
from uvr_loan.data.sources import load_raw

PANEL_PATH = ROOT / "data" / "processed" / "monthly_panel.csv"


def to_month_end(s: pd.Series) -> pd.Series:
    """Last available value of each calendar month, indexed by monthly period."""
    return s.groupby(s.index.to_period("M")).last()


def build_monthly_panel(
    raw: dict[str, pd.Series], rate_columns: Iterable[str], start: str, end: str
) -> pd.DataFrame:
    """One row per month between `start` and `end`; rates go from % to decimals.

    Raises ValueError if any month is missing a value.
    """
    months = pd.period_range(start, end, freq="M")
    panel = pd.DataFrame({name: to_month_end(s) for name, s in raw.items()}).reindex(months)
    for col in rate_columns:
        panel[col] = panel[col] / 100

    missing = panel[panel.isna().any(axis=1)]
    if not missing.empty:
        raise ValueError(f"Missing data in months: {', '.join(str(m) for m in missing.index)}")
    return panel


def load_monthly_panel(cfg: dict[str, Any]) -> pd.DataFrame:
    """Panel from t0 back to `data.start` up to the last complete month of the horizon."""
    data = cfg["data"]
    end = pd.Period(cfg["backtest"]["t0"], "M") + cfg["backtest"]["horizon_months"]
    return build_monthly_panel(load_raw(cfg), data["rate_series"], data["start"][:7], str(end))


if __name__ == "__main__":
    panel = load_monthly_panel(load_assumptions())
    PANEL_PATH.parent.mkdir(parents=True, exist_ok=True)
    panel.to_csv(PANEL_PATH, index_label="month")
    print(panel.loc["2016-10":"2016-12"])
    print(f"{len(panel)} months written to {PANEL_PATH}")

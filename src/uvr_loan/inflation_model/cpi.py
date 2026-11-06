"""Monthly CPI rebuilt from the UVR, its seasonality and the realized inflation used to correct the forecasts.

The UVR is indexed to the CPI with a lag: the UVR of the 15th of month m grows relative to the 15th of m - 1
by the CPI of month m - 2 (`UVR_LAG_MONTHS`). Annual rates here are continuously compounded.
"""

import numpy as np
import pandas as pd

UVR_LAG_MONTHS = 2  # how the UVR is defined: its monthly change reflects the CPI of two months before


def uvr_on_day_15(uvr: pd.Series) -> pd.Series:
    """Last UVR of each month up to the 15th (the UVR changes on the 16th), indexed by monthly period."""
    up_to_15 = uvr[uvr.index.day <= 15]
    return up_to_15.groupby(up_to_15.index.to_period("M")).last()


def monthly_cpi(uvr: pd.Series) -> pd.Series:
    """Log CPI of each month (not annualized): ln(UVR15(k + 2) / UVR15(k + 1))."""
    change = np.log(uvr_on_day_15(uvr)).diff().dropna()
    change.index = change.index - UVR_LAG_MONTHS
    return change.rename("cpi")


def cpi_target(uvr: pd.Series, origin: pd.Timestamp | pd.Period, horizon_months: int = 6) -> float:
    """Annualized inflation of the `horizon_months` months after the month of `origin`, from the UVR."""
    level = uvr_on_day_15(uvr)
    month = pd.Period(origin, "M")
    start, end = month + UVR_LAG_MONTHS, month + horizon_months + UVR_LAG_MONTHS
    if start not in level.index or end not in level.index:
        raise ValueError(f"The UVR does not reach {end} (last data {level.index.max()})")
    return float(np.log(level[end] / level[start]) / (horizon_months / 12))


def seasonal_factors(cpi: pd.Series, until: pd.Period) -> pd.Series:
    """Mean deviation (annualized) of each calendar month from the average of its year, by month number 1..12.

    Only complete years of `cpi` up to `until` are used, so the factors are the ones known at that month.
    """
    annualized = 12 * cpi[cpi.index <= until]
    months_per_year = annualized.groupby(annualized.index.year).transform("size")
    annualized = annualized[months_per_year == 12]
    if annualized.empty:
        raise ValueError("There is no complete year of CPI to estimate the seasonality")
    deviation = annualized - annualized.groupby(annualized.index.year).transform("mean")
    return deviation.groupby(deviation.index.month).mean().sort_index()


def seasonal_adjustment(
    factors: pd.Series, origin: pd.Timestamp | pd.Period, horizon_months: int = 6
) -> float:
    """Mean seasonal factor of the `horizon_months` months after the month of `origin`."""
    month = pd.Period(origin, "M")
    return float(factors.loc[[(month + i).month for i in range(1, horizon_months + 1)]].mean())

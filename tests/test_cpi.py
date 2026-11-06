import numpy as np
import pandas as pd
import pytest
from model_helpers import SEASONAL_PATTERN, uvr_from_cpi

from uvr_loan.inflation_model.cpi import (
    UVR_LAG_MONTHS,
    cpi_target,
    monthly_cpi,
    seasonal_adjustment,
    seasonal_factors,
)


@pytest.fixture
def seasonal_cpi() -> pd.Series:
    months = pd.period_range("2000-01", "2012-12", freq="M")
    return pd.Series([0.003 + SEASONAL_PATTERN[m.month - 1] * 0.5 for m in months], index=months)


@pytest.fixture
def uvr(seasonal_cpi) -> pd.Series:
    return uvr_from_cpi(seasonal_cpi)


def test_the_uvr_lag_is_two_months():
    assert UVR_LAG_MONTHS == 2


def test_monthly_cpi_recovers_the_cpi_the_uvr_was_built_from(seasonal_cpi, uvr):
    recovered = monthly_cpi(uvr)
    common = recovered.index.intersection(seasonal_cpi.index)
    assert len(common) > 100
    np.testing.assert_allclose(recovered.loc[common], seasonal_cpi.loc[common], atol=1e-12)


def test_cpi_target_is_the_mean_annualised_cpi_of_the_next_months(seasonal_cpi, uvr):
    origin = pd.Timestamp("2005-03-31")
    assert cpi_target(uvr, origin) == pytest.approx(12 * seasonal_cpi.loc["2005-04":"2005-09"].mean())
    assert cpi_target(uvr, origin, horizon_months=3) == pytest.approx(
        12 * seasonal_cpi.loc["2005-04":"2005-06"].mean()
    )


def test_cpi_target_beyond_the_data_raises(uvr):
    with pytest.raises(ValueError, match="UVR"):
        cpi_target(uvr, pd.Timestamp("2012-12-31"))


def test_seasonal_factors_are_zero_for_a_constant_cpi():
    months = pd.period_range("2000-01", "2010-12", freq="M")
    factors = seasonal_factors(pd.Series(0.004, index=months), until=pd.Period("2010-12", "M"))
    np.testing.assert_allclose(factors.to_numpy(), 0.0, atol=1e-12)


def test_seasonal_factors_recover_the_pattern(seasonal_cpi):
    factors = seasonal_factors(seasonal_cpi, until=pd.Period("2012-12", "M"))
    np.testing.assert_allclose(
        factors.to_numpy(), 12 * 0.5 * (SEASONAL_PATTERN - SEASONAL_PATTERN.mean()), atol=1e-12
    )


def test_seasonal_factors_ignore_data_after_the_cutoff(seasonal_cpi):
    until = pd.Period("2008-12", "M")
    altered = seasonal_cpi.copy()
    altered.loc["2009-01":] += 0.05
    pd.testing.assert_series_equal(seasonal_factors(seasonal_cpi, until), seasonal_factors(altered, until))


def test_seasonal_factors_need_a_complete_year():
    months = pd.period_range("2000-01", "2000-08", freq="M")
    with pytest.raises(ValueError, match="complete year"):
        seasonal_factors(pd.Series(0.004, index=months), until=pd.Period("2000-08", "M"))


def test_seasonal_adjustment_is_the_mean_of_the_next_months(seasonal_cpi):
    factors = seasonal_factors(seasonal_cpi, until=pd.Period("2012-12", "M"))
    adjustment = seasonal_adjustment(factors, pd.Period("2005-03", "M"))
    assert adjustment == pytest.approx(factors.loc[[4, 5, 6, 7, 8, 9]].mean())

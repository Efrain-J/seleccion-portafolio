import warnings

import numpy as np
import pandas as pd
import pytest

from uvr_loan.inflation import project_uvr, scenarios, trailing_inflation


def test_zero_inflation_keeps_uvr_constant():
    np.testing.assert_allclose(project_uvr(250.0, 0.0, 6), np.full(6, 250.0))


def test_uvr_grows_by_annual_inflation_after_12_months():
    path = project_uvr(250.0, 0.05, 12)
    assert len(path) == 12
    assert path[-1] == pytest.approx(250.0 * 1.05)
    assert np.all(np.diff(path) > 0)


def test_trailing_inflation_annualizes_the_last_months():
    uvr = pd.Series([90.0, 100.0, 100.0, 105.0])  # +5 % over the last 2 months
    assert trailing_inflation(uvr, 2) == pytest.approx(1.05**6 - 1)


def test_trailing_inflation_ignores_older_months():
    uvr = pd.Series([50.0, 100.0, 101.0])
    assert trailing_inflation(uvr, 1) == pytest.approx(1.01**12 - 1)


def test_trailing_inflation_needs_enough_history():
    with pytest.raises(ValueError, match="6 months"):
        trailing_inflation(pd.Series([100.0, 101.0]), 6)


def test_scenarios_use_the_trailing_base_and_config_shocks(cfg):
    s = cfg["inflation_scenarios"]
    months = s["base_lookback_months"]
    uvr = pd.Series(100.0 * 1.01 ** np.arange(months + 1))  # 1 % per month
    base = 1.01**12 - 1
    result = scenarios(cfg, uvr)
    assert result["base"] == pytest.approx(base)
    assert result["high"] == pytest.approx(base + s["high_shock_pp"] / 100)
    assert result["low"] == pytest.approx(base + s["low_shock_pp"] / 100)


def test_plans_use_the_same_inflation_scenario(cfg):
    """Warns (does not fail) if the plans decide with different inflation: their results would not be comparable."""
    used = {
        "conservative.fic_sizing_scenario": cfg["conservative"]["fic_sizing_scenario"],
        "cdt_ladder.deflator_scenario": cfg["cdt_ladder"]["deflator_scenario"],
        "ldi.floor_scenario": cfg["ldi"]["floor_scenario"],
    }
    if len(set(used.values())) > 1:
        warnings.warn(f"The plans use different inflation scenarios, their results are not comparable: {used}")

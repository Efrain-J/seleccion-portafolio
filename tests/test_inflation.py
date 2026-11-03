import numpy as np
import pytest

from uvr_loan.inflation import project_uvr, scenarios


def test_zero_inflation_keeps_uvr_constant():
    np.testing.assert_allclose(project_uvr(250.0, 0.0, 6), np.full(6, 250.0))


def test_uvr_grows_by_annual_inflation_after_12_months():
    path = project_uvr(250.0, 0.05, 12)
    assert len(path) == 12
    assert path[-1] == pytest.approx(250.0 * 1.05)
    assert np.all(np.diff(path) > 0)


def test_scenarios_follow_config(cfg):
    s = cfg["inflation_scenarios"]
    result = scenarios(cfg)
    assert result["base"] == pytest.approx(s["base_annual"])
    assert result["high"] == pytest.approx(s["base_annual"] + s["high_shock_pp"] / 100)
    assert result["low"] == pytest.approx(s["base_annual"] + s["low_shock_pp"] / 100)

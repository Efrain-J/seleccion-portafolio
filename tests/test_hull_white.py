import numpy as np
import pandas as pd
import pytest

from uvr_loan.inflation_model.hull_white import simulate_hull_white

TENORS = np.arange(1, 11)
KAPPAS = (0.11, 0.13)


@pytest.fixture
def spot() -> np.ndarray:
    """Smooth, upward-sloping curve in decimals."""
    return 0.04 + 0.01 * (1 - np.exp(-TENORS / 3.0))


def simulate(spot, sigma=0.005, n_paths=200, seed=123456, steps_per_year=1, years=10):
    sigma = np.full(TENORS.shape, sigma)
    return simulate_hull_white(5, KAPPAS, TENORS, sigma, spot, steps_per_year, years, n_paths, seed)


def test_output_keys_and_shapes(spot):
    out = simulate(spot, n_paths=50)
    assert set(out) == {"forward_rates", "discount_factors", "spot_rates", "time_axis"}
    for key in ("forward_rates", "discount_factors", "spot_rates"):
        assert out[key].shape == (50, len(TENORS))
    np.testing.assert_allclose(out["time_axis"], TENORS)


def test_monthly_steps_give_a_column_per_month(spot):
    out = simulate(spot, n_paths=20, steps_per_year=12, years=1)
    assert out["spot_rates"].shape == (20, 12)
    assert out["time_axis"][5] == pytest.approx(0.5)


def test_values_are_finite(spot):
    out = simulate(spot)
    for key in ("forward_rates", "discount_factors", "spot_rates"):
        assert np.isfinite(out[key].to_numpy()).all()


def test_same_seed_is_reproducible_and_does_not_touch_the_global_seed(spot):
    np.random.seed(7)
    before = np.random.get_state()[1].copy()
    a = simulate(spot)["spot_rates"]
    assert (np.random.get_state()[1] == before).all()
    pd.testing.assert_frame_equal(a, simulate(spot)["spot_rates"])


def test_different_seeds_differ(spot):
    assert not simulate(spot, seed=1)["spot_rates"].equals(simulate(spot, seed=2)["spot_rates"])


def test_zero_sigma_reproduces_the_input_curve(spot):
    out = simulate(spot, sigma=1e-12, n_paths=20)
    np.testing.assert_allclose(out["spot_rates"].mean().to_numpy(), spot, atol=1e-6)


@pytest.mark.parametrize("idx", [0, 4, 9])
def test_mean_discount_factor_matches_the_input_curve(spot, idx):
    """Hull-White is calibrated to today's curve: E[DF(t)] must equal exp(-t * spot(t))."""
    out = simulate(spot, n_paths=100_000)
    simulated = out["discount_factors"].iloc[:, idx].mean()
    assert simulated == pytest.approx(np.exp(-TENORS[idx] * spot[idx]), rel=2e-3)

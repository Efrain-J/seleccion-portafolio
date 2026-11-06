"""One-factor Hull-White simulation of a rate curve, with time-dependent mean reversion and volatility.

Ported from an R implementation; the formulas and the order of operations are kept as they were so that the
numbers do not change. Quirks to know before touching it:

- `kappa_switch` is a time in years (kappa changes from `kappas[0]` to `kappas[1]` there) and, at the same time, the
  number of sigma nodes that are used: only `sigma[:kappa_switch]` enters the model, and the last of those volatilities is
  held constant after its tenor. The volatilities of the later nodes are ignored.
- The first step uses the full Hull-White formula, like the others (the R code left it deterministic).
- `_vol_integral` picks the volatility of the interval that contains `t`; its index adjustments (`M`, `last`) are
  the ones of the R code.
- The curve is interpolated linearly in the tenor, held flat outside the given tenors.
- The paths come from `np.random.RandomState(seed)`: the same stream as the old global `np.random.seed(seed)`.

The expected value of each simulated discount factor is the discount factor of the input curve (the model is
calibrated to it), so the mean of the paths reproduces the input curve and only the dispersion is new.
"""

import numpy as np
import pandas as pd
from scipy.interpolate import interp1d


def simulate_hull_white(
    kappa_switch: int,
    kappas: tuple[float, float],
    tenors: np.ndarray,
    sigma: np.ndarray,
    spot: np.ndarray,
    steps_per_year: int,
    years: int,
    n_paths: int,
    seed: int,
) -> dict[str, pd.DataFrame | np.ndarray]:
    """Simulate `n_paths` paths of the curve, `steps_per_year` steps a year for `years` years.

    `tenors` (years), `sigma` (volatility of each node) and `spot` (decimal rate of each node) describe today's
    curve. Returns the DataFrames `forward_rates`, `discount_factors` and `spot_rates` (one row per path, one column
    `T_<time>` per step) and `time_axis`, the time in years of each column.
    """
    tenors = np.array(tenors, dtype=float)
    sigma = np.array(sigma, dtype=float)
    spot = np.array(spot, dtype=float)

    switch = float(kappa_switch)
    kappa1, kappa2 = kappas
    vol_tenors, vols = tenors[:kappa_switch], sigma[:kappa_switch]
    n_vols = len(vols)

    def vol_integral(t: float, a: float, b: float) -> float:
        """Integral over [0, t] of sigma(s)^2 * a * exp(b * s) ds, with sigma piecewise constant."""
        value = 0.0
        known = np.where(vol_tenors <= t)[0]
        m = 0 if len(known) == 0 else known[-1] + 1
        if b == 0:
            if m == 0:
                value += (vols[0] ** 2) * a * t
            else:
                for i in range(m):
                    previous = 0 if i == 0 else vol_tenors[i - 1]
                    value += (vols[i] ** 2) * a * (vol_tenors[i] - previous)
                last = m - 1 if m == n_vols else m
                value += (vols[last] ** 2) * a * (t - vol_tenors[m - 1])
        else:
            if m == 0:
                value += (vols[0] ** 2) * a / b * (np.exp(b * t) - 1)
            else:
                for i in range(m):
                    previous = 1 if i == 0 else np.exp(b * vol_tenors[i - 1])
                    value += (vols[i] ** 2) * a / b * (np.exp(b * vol_tenors[i]) - previous)
                last = m - 1 if m == n_vols else m
                value += (vols[last] ** 2) * a / b * (np.exp(b * t) - np.exp(b * vol_tenors[m - 1]))
        return value

    def decay(s: float, t: float) -> float:
        """Factor that carries the state from s to t: exp of minus the integral of kappa."""
        if switch <= s:
            return np.exp(-kappa2 * (t - s))
        if t < switch:
            return np.exp(-kappa1 * (t - s))
        return np.exp(-kappa1 * (switch - s) - kappa2 * (t - switch))

    def b_single(s: float, t: float, kappa: float) -> float:
        return (1.0 - np.exp(-kappa * (t - s))) / kappa

    def b_factor(s: float, t: float) -> float:
        """Sensitivity of the price of a bond maturing at t to the state at s."""
        if switch <= s:
            return b_single(s, t, kappa2)
        if t < switch:
            return b_single(s, t, kappa1)
        return b_single(s, switch, kappa1) + np.exp(-kappa1 * (switch - s)) * b_single(switch, t, kappa2)

    def zeta(t: float) -> float:
        """Variance of the state at t."""
        if t < switch:
            return np.exp(-2 * kappa1 * t) * vol_integral(t, 1, 2 * kappa1)
        first = np.exp(-2 * kappa2 * (t - switch) - 2 * kappa1 * switch) * vol_integral(switch, 1, 2 * kappa1)
        second = np.exp(-2 * kappa2 * t) * (
            vol_integral(t, 1, 2 * kappa2) - vol_integral(switch, 1, 2 * kappa2)
        )
        return first + second

    def z_single(t: float, kappa: float) -> float:
        i1 = np.exp(-kappa * t) * vol_integral(t, 1, kappa) / kappa
        i2 = np.exp(-2 * kappa * t) * vol_integral(t, 1, 2 * kappa) / kappa
        return i1 - i2

    def z_term(t: float) -> float:
        if t < switch:
            return z_single(t, kappa1)
        i1 = np.exp(-kappa2 * (t - switch)) * z_single(switch, kappa1)
        i2 = (
            np.exp(-kappa2 * (t - switch))
            * b_factor(switch, t)
            * np.exp(-2 * kappa1 * switch)
            * vol_integral(switch, 1, 2 * kappa1)
        )
        i3 = np.exp(-kappa2 * t) * vol_integral(switch, 1, kappa2) / kappa2
        i4 = np.exp(-2 * kappa2 * t) * vol_integral(switch, 1, 2 * kappa2) / kappa2
        return i1 + i2 + z_single(t, kappa2) - i3 + i4

    def omega(t: float, maturity: float) -> float:
        """Convexity term of the bond price between t and `maturity`."""
        return -b_factor(t, maturity) * (2.0 * z_term(t) + b_factor(t, maturity) * zeta(t))

    dt = 1.0 / steps_per_year
    n_steps = round(years * steps_per_year)
    time_axis = np.linspace(dt, years, n_steps)

    # Today's curve at the step times (linear, flat outside the tenors) and its discount factors.
    curve = interp1d(tenors, spot, kind="linear", bounds_error=False, fill_value=(spot[0], spot[-1]))
    initial_discount = np.exp(-time_axis * curve(time_axis))

    a_step = np.zeros(n_steps)
    zeta_step = np.zeros(n_steps)
    b_step = np.zeros(n_steps)
    omega_step = np.zeros(n_steps)
    for n in range(n_steps):
        t_now = time_axis[n]
        t_before = t_now - dt
        a_step[n] = decay(t_before, t_now)
        zeta_step[n] = zeta(t_now)
        b_step[n] = b_factor(t_before, t_now)
        omega_step[n] = omega(t_before, t_now)

    # Standard deviation of the state innovation of each step.
    innovation_std = np.zeros(n_steps)
    innovation_std[0] = np.sqrt(zeta_step[0])
    innovation_std[1:] = np.sqrt(zeta_step[1:] - (a_step[1:] ** 2) * zeta_step[:-1])

    # Ratio of today's discount factors P(0, t + dt) / P(0, t); P(0, 0) = 1.
    discount_ratio = np.zeros(n_steps)
    discount_ratio[0] = initial_discount[0]
    discount_ratio[1:] = initial_discount[1:] / initial_discount[:-1]

    # Rows are steps and columns paths until the end, where they are transposed.
    rng = np.random.RandomState(seed)
    bond_price = np.zeros((n_steps, n_paths))
    state = rng.normal(0, 1, n_paths) * innovation_std[0]
    bond_price[0, :] = discount_ratio[0] * np.exp(-state * b_step[0] + 0.5 * omega_step[0])
    for n in range(1, n_steps):
        state = state * a_step[n] + rng.normal(0, 1, n_paths) * innovation_std[n]
        bond_price[n, :] = discount_ratio[n] * np.exp(-state * b_step[n] + 0.5 * omega_step[n])

    forward = -np.log(bond_price) / dt  # rate of each step
    discount = np.cumprod(bond_price, axis=0)
    spot_rates = -np.log(discount) / time_axis[:, None]  # yield from 0 to each step

    columns = [f"T_{round(t, 2)}" for t in time_axis]
    tables = {
        "forward_rates": forward.T,
        "discount_factors": discount.T,
        "spot_rates": spot_rates.T,
    }
    out: dict[str, pd.DataFrame | np.ndarray] = {}
    for name, values in tables.items():
        out[name] = pd.DataFrame(values, columns=columns).rename_axis("path")
    out["time_axis"] = time_axis
    return out

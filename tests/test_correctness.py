"""Correctness checks of the backtest on synthetic data that changes every month.

- No look-ahead: replacing every month after a cut with garbage must not change any result up to
  the cut (and a deliberately leaky plan must be caught).
- Results use observed data: payments with the UVR of their own month.
- Accounting: money is conserved at reviews, wealth = FIC + CDT + ETF, nothing negative.
- Plan 2 executes exactly the LP's purchases of the review.
"""

import numpy as np
import pandas as pd
import pytest
from helpers import make_cfg, make_panel, make_schedule

from uvr_loan import backtest
from uvr_loan.backtest import PLANS, run_backtest

HORIZON = 24
TERMS = {3: "cdt_90d_ea", 6: "cdt_180d_ea", 12: "cdt_360d_ea"}
PAYMENTS = {m: 20.0 + m for m in range(7, HORIZON + 1)} | {12: 120.0}
ETFS = ["icolcap", "cspx"]
ALL_PLANS = ["conservative", "cdt_ladder", "ldi"]


def varied_panel(cfg, seed=0):
    """A panel whose UVR, rates, FIC return and ETF price change every month."""
    panel = make_panel(cfg)
    n = len(panel)
    rng = np.random.default_rng(seed)
    panel["uvr_cop"] = 250 * np.cumprod(1 + rng.uniform(0.0, 0.01, n))
    for column in TERMS.values():
        panel[column] = rng.uniform(0.03, 0.12, n)
    panel["fic_ret_m"] = rng.uniform(0.002, 0.008, n)
    panel["fic_rate_ea"] = (1 + panel["fic_ret_m"]) ** 12 - 1
    for name in ETFS:
        panel[f"{name}_price_cop"] = 100 * np.cumprod(1 + rng.normal(0, 0.05, n))
        panel[f"{name}_vol_ea"] = rng.uniform(0.1, 0.3, n)
    return panel


def scramble_after(panel, cfg, cut):
    """Copy of the panel where every month after t0 + cut is garbage."""
    bad = panel.copy()
    late = bad.index > pd.Period(cfg["backtest"]["t0"], "M") + cut
    rng = np.random.default_rng(99)
    k = int(late.sum())
    bad.loc[late, "uvr_cop"] *= 3 * rng.uniform(0.5, 1.5, k)
    for column in TERMS.values():
        bad.loc[late, column] = rng.uniform(0.0, 0.5, k)
    bad.loc[late, "fic_ret_m"] = rng.uniform(-0.05, 0.1, k)
    bad.loc[late, "fic_rate_ea"] = rng.uniform(-0.3, 1.0, k)
    for name in ETFS:
        bad.loc[late, f"{name}_price_cop"] *= 0.1
        bad.loc[late, f"{name}_vol_ea"] = rng.uniform(0.01, 1.0, k)
    return bad


@pytest.fixture
def cfg():
    return {
        **make_cfg(horizon=HORIZON, terms=TERMS),
        "initial_capital_cop": 1_000_000.0,
    }  # covers the payments


@pytest.fixture
def schedule():
    return make_schedule(PAYMENTS, horizon=HORIZON)


def same_until(panel, scrambled, schedule, cfg, plan, cut):
    base = run_backtest(panel, schedule, cfg, plan)
    other = run_backtest(scrambled, schedule, cfg, plan)
    pd.testing.assert_frame_equal(base[base["month"] <= cut], other[other["month"] <= cut], check_exact=True)
    assert not base[base["month"] > cut].equals(
        other[other["month"] > cut]
    )  # the garbage does have an effect


@pytest.mark.parametrize("plan", ALL_PLANS)
@pytest.mark.parametrize("cut", [6, 12, 18])
def test_no_lookahead(cfg, schedule, plan, cut):
    panel = varied_panel(cfg)
    same_until(panel, scramble_after(panel, cfg, cut), schedule, cfg, plan, cut)


def uvr_leak(current, tau, history, free_cop, lots, payment_schedule, cfg):
    """Plan 1 that moves money from the FIC to the CDT according to next month's UVR."""
    future_uvr = current["panel"].loc[history.index[-1] + 1, "uvr_cop"]  # the leak
    alloc = backtest.conservative_strategy(tau, history, free_cop, lots, payment_schedule, cfg)
    shift = min(alloc.fic_cop, free_cop * future_uvr / 10_000)
    shifted = [{**lot, "principal_cop": lot["principal_cop"] + shift} for lot in alloc.lots]
    return alloc._replace(fic_cop=alloc.fic_cop - shift, lots=shifted)


def vol_leak(current, tau, history, free_cop, lots, payment_schedule, cfg):
    """Plan 3 that moves money between its ETFs according to next month's volatility."""
    future_vol = current["panel"].loc[history.index[-1] + 1, "icolcap_vol_ea"]  # the leak
    alloc = backtest.ldi_strategy(tau, history, free_cop, lots, payment_schedule, cfg)
    shift = alloc.etf_cop["cspx"] * min(future_vol, 1.0) / 2
    etfs = {"icolcap": alloc.etf_cop["icolcap"] + shift, "cspx": alloc.etf_cop["cspx"] - shift}
    return alloc._replace(etf_cop=etfs)


@pytest.mark.parametrize("leak", [uvr_leak, vol_leak], ids=["plan-1-uvr", "plan-3-volatility"])
def test_the_lookahead_test_catches_a_leak(monkeypatch, cfg, schedule, leak):
    """A plan that peeks at next month's data must make the perturbation test fail."""
    panel = varied_panel(cfg)
    scrambled = scramble_after(panel, cfg, 6)
    current = {}

    def leaky(*args):
        return leak(current, *args)

    monkeypatch.setitem(PLANS, "leaky", leaky)
    original_run = backtest.run_backtest

    def run(panel_, *args):
        current["panel"] = panel_
        return original_run(panel_, *args)

    with pytest.raises(AssertionError):
        base, other = run(panel, schedule, cfg, "leaky"), run(scrambled, schedule, cfg, "leaky")
        pd.testing.assert_frame_equal(base[base["month"] <= 6], other[other["month"] <= 6], check_exact=True)


@pytest.mark.parametrize("plan", ALL_PLANS)
def test_payments_use_the_observed_uvr_of_their_month(cfg, schedule, plan):
    panel = varied_panel(cfg)
    results = run_backtest(panel, schedule, cfg, plan).set_index("month")
    for month, amount_uvr in PAYMENTS.items():
        observed = panel.loc[pd.Period(cfg["backtest"]["t0"], "M") + month, "uvr_cop"]
        assert results.loc[month, "payment_cop"] == pytest.approx(amount_uvr * observed)
        assert results.loc[month, "uvr_cop"] == observed


@pytest.mark.parametrize("plan", ALL_PLANS)
def test_money_is_conserved_at_reviews(monkeypatch, cfg, schedule, plan):
    gaps = []
    original = PLANS[plan]

    def recorder(tau, history, free_cop, lots, payment_schedule, cfg):
        alloc = original(tau, history, free_cop, lots, payment_schedule, cfg)
        spent = alloc.fic_cop + sum(alloc.etf_cop.values()) + sum(lot["principal_cop"] for lot in alloc.lots)
        gaps.append(free_cop - spent)
        return alloc

    monkeypatch.setitem(PLANS, plan, recorder)
    run_backtest(varied_panel(cfg), schedule, cfg, plan)
    assert len(gaps) == HORIZON // 6
    assert max(abs(g) for g in gaps) < 1e-6


@pytest.mark.parametrize("plan", ALL_PLANS)
def test_wealth_identity_and_nothing_negative(cfg, schedule, plan):
    results = run_backtest(varied_panel(cfg), schedule, cfg, plan)
    total = results["fic_cop"] + results["cdt_cop"] + results["etf_cop"]
    assert (results["wealth_cop"] - total).abs().max() < 1e-6
    for column in ["fic_cop", "cdt_cop", "etf_cop", "shortfall_cop", "etf_sold_cop"]:
        assert (results[column] >= -1e-9).all(), column
    assert results["cdt_cop"].iloc[-1] == pytest.approx(0.0)  # every CDT matures by the horizon


def test_ladder_executes_exactly_the_lp_purchases(monkeypatch, cfg, schedule):
    solutions, executed = {}, {}
    original_lp, original_plan = backtest.ladder_purchases, PLANS["cdt_ladder"]

    def lp(tau, *args, **kwargs):
        solutions[tau] = original_lp(tau, *args, **kwargs)
        return solutions[tau]

    def plan(tau, history, free_cop, lots, payment_schedule, cfg):
        alloc = original_plan(tau, history, free_cop, lots, payment_schedule, cfg)
        executed[tau] = (history["uvr_cop"].iloc[-1], history.iloc[-1], alloc.lots)
        return alloc

    monkeypatch.setattr(backtest, "ladder_purchases", lp)
    monkeypatch.setitem(PLANS, "cdt_ladder", plan)
    run_backtest(varied_panel(cfg), schedule, cfg, "cdt_ladder")
    for tau, (uvr, row, lots) in executed.items():
        bought = {lot["maturity_month"] - tau: lot for lot in lots}
        for term, amount_uvr in solutions[tau].items():
            if amount_uvr > 0:
                assert bought[term]["principal_cop"] == pytest.approx(amount_uvr * uvr)
                assert bought[term]["rate_ea"] == row[TERMS[term]]
                assert bought[term]["buy_month"] == tau
            else:
                assert term not in bought

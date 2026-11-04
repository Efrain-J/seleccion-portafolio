"""Synthetic config, panel and payment schedule shared by the backtest tests."""

import pandas as pd


def make_cfg(cdt_weight=0.90, horizon=12, k=6, terms=None):
    return {
        "initial_capital_cop": 1_000.0,
        "backtest": {"t0": "2020-01", "horizon_months": horizon, "review_every_months": k},
        "conservative": {"cdt_weight": cdt_weight, "fic_sizing_scenario": "base"},
        "inflation_scenarios": {"base_lookback_months": 6, "high_shock_pp": 0.0, "low_shock_pp": 0.0},
        "cdt_ladder": {"deflator_scenario": "base", "term_columns": terms or {6: "cdt_180d_ea"}},
    }


HISTORY = 12  # months of data before t0, as the real panel has (it starts in 2015)


def make_panel(cfg, uvr=1.0, fic=0.0, cdt_180=0.0, etf=100.0, cdt_90=0.0, cdt_360=0.0):
    """Monthly panel from t0 - HISTORY to the end of the horizon.

    Each column is a scalar or a list of horizon + 1 values (months 0..horizon); the history
    before t0 repeats the value of month 0.
    """
    bt = cfg["backtest"]
    start = pd.Period(bt["t0"], "M") - HISTORY
    months = pd.period_range(start, periods=HISTORY + bt["horizon_months"] + 1, freq="M")
    columns = {
        "uvr_cop": uvr,
        "cdt_90d_ea": cdt_90,
        "cdt_180d_ea": cdt_180,
        "cdt_360d_ea": cdt_360,
        "etf_price_cop": etf,
        "fic_rate_ea": fic,  # `fic` is an annual rate (scalar) in these tests
        "fic_ret_m": (1 + fic) ** (1 / 12) - 1,
    }
    padded = {name: [v[0]] * HISTORY + list(v) if isinstance(v, list) else v for name, v in columns.items()}
    return pd.DataFrame(padded, index=months)


def make_schedule(payments, horizon=12):
    months = range(1, horizon + 1)
    return pd.DataFrame({"month": months, "total_payment_uvr": [payments.get(m, 0.0) for m in months]})

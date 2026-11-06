"""Backtest of every plan with three inflation bases: trailing UVR, forecast median and forecast p99.5.

The forecast file (`inflation_scenarios.forecast_file`) has the 6-month inflation distribution of the
best model of the hull_white project at the close of every month. The base inflation of the scenarios is
replaced by one of its statistics; high and low keep their shocks. The runs start in `T0` (May 2016) because
the panel is complete from then on: the FIC returns start in Feb 2016 and the ICOLCAP volatility needs 36
months of returns since its listing in May 2013.

Run `python -m uvr_loan.forecast_runs` to write the results to results/forecast_runs/.
"""

import copy
from typing import Any

import numpy as np
import pandas as pd

from uvr_loan.amortization import schedule
from uvr_loan.backtest import PLANS, run_backtest, summary
from uvr_loan.cashflows import decision_months, month_to_period
from uvr_loan.config import RESULTS_DIR, load_assumptions
from uvr_loan.inflation import scenarios

T0 = "2016-05"
OUT_DIR = RESULTS_DIR / "forecast_runs"

# Overrides of `inflation_scenarios` for each case.
CASES: dict[str, dict[str, str]] = {
    "trailing": {"source": "trailing"},
    "median": {"source": "forecast", "forecast_stat": "median_ea"},
    "p995": {"source": "forecast", "forecast_stat": "p995_ea"},
}


def case_cfg(cfg: dict[str, Any], case: str, t0: str | None = None) -> dict[str, Any]:
    """Copy of `cfg` with the inflation source of `case` (and `t0`, if given). The original is not modified."""
    out = copy.deepcopy(cfg)
    if t0 is not None:
        out["backtest"]["t0"] = t0
    out["inflation_scenarios"].update(CASES[case])
    return out


def pad_uvr_history(panel: pd.DataFrame, uvr: pd.Series, months: int = 12) -> pd.DataFrame:
    """Panel with `months` earlier rows that only have `uvr_cop` (the other columns are NaN).

    The trailing inflation of the first reviews needs more UVR history than the panel has (it starts with the
    FIC data in Jan 2016); the UVR itself is known long before. `uvr` is the month-end UVR (monthly period index).
    Those rows are only read as history by `scenarios`: the backtest checks and uses the months from t0 on.
    """
    earlier = pd.period_range(panel.index[0] - months, panel.index[0] - 1, freq="M")
    missing = earlier.difference(uvr.index)
    if len(missing):
        raise ValueError(f"The UVR series has no data for months: {', '.join(map(str, missing))}")
    extra = pd.DataFrame({"uvr_cop": uvr.loc[earlier]}, index=earlier).reindex(columns=panel.columns)
    return pd.concat([extra, panel])


def base_inflation_log(panel: pd.DataFrame, cfg: dict[str, Any]) -> pd.DataFrame:
    """Base inflation used at each review next to the UVR inflation realized in the following 6 months (annual)."""
    bt, uvr = cfg["backtest"], panel["uvr_cop"]
    rows = {}
    for m in decision_months(bt):
        month = month_to_period(bt["t0"], m)
        later = month + 6
        realised = (uvr[later] / uvr[month]) ** 2 - 1 if later in uvr.index else np.nan
        rows[str(month)] = {"base": scenarios(cfg, uvr.loc[:month])["base"], "realised_next_6m": realised}
    return pd.DataFrame.from_dict(rows, orient="index")


def run_cases(
    panel: pd.DataFrame, payment_schedule: pd.DataFrame, cfg: dict[str, Any], t0: str = T0
) -> dict[str, dict[str, Any]]:
    """For each case: `results` (plan -> monthly DataFrame), `summary` (metric x plan) and the `log` of base inflation."""
    out = {}
    for case in CASES:
        c = case_cfg(cfg, case, t0)
        results = {plan: run_backtest(panel, payment_schedule, c, plan) for plan in PLANS}
        out[case] = {
            "results": results,
            "summary": pd.DataFrame({plan: summary(r) for plan, r in results.items()}),
            "log": base_inflation_log(panel, c),
        }
    return out


def comparison(out: dict[str, dict[str, Any]]) -> pd.DataFrame:
    """One row per (plan, case) with the summary metrics."""
    return (
        pd.concat({case: v["summary"].T for case, v in out.items()})
        .swaplevel()
        .sort_index(sort_remaining=False)
    )


if __name__ == "__main__":
    from uvr_loan.data.cleaning import load_monthly_panel, to_month_end
    from uvr_loan.data.sources import load_raw

    cfg = load_assumptions()
    panel = load_monthly_panel(case_cfg(cfg, "trailing", T0))
    panel = pad_uvr_history(panel, to_month_end(load_raw(cfg)["uvr_cop"]))
    out = run_cases(panel, schedule(cfg["loan"]), cfg, T0)

    for case, v in out.items():
        folder = OUT_DIR / case
        folder.mkdir(parents=True, exist_ok=True)
        for plan, results in v["results"].items():
            results.to_csv(folder / f"backtest_{plan}.csv", index=False)
        v["summary"].to_csv(folder / "summary.csv", index_label="metric")
        v["log"].to_csv(folder / "base_inflation.csv", index_label="month")
    table = comparison(out)
    table.to_csv(OUT_DIR / "comparison.csv", index_label=["plan", "case"])

    shown = [
        "shortfall_months",
        "total_shortfall_cop",
        "final_wealth_net_cop",
        "annual_return",
        "max_drawdown",
    ]
    print(table[shown].to_string(float_format=lambda x: f"{x:,.4f}"))
    base = pd.DataFrame({case: v["log"]["base"] for case, v in out.items()})
    base["realised_next_6m"] = out["trailing"]["log"]["realised_next_6m"]
    print("\nBase inflation at each review (annual) and the realized UVR inflation of the next 6 months:")
    print(base.to_string(float_format=lambda x: f"{x:.4f}"))
    print(f"Written to {OUT_DIR}")

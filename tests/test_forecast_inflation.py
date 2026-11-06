import copy

import numpy as np
import pandas as pd
import pytest
from helpers import make_cfg, make_panel, make_schedule

from uvr_loan.forecast_runs import CASES, base_inflation_log, case_cfg, pad_uvr_history, run_cases
from uvr_loan.inflation import forecast_base, scenarios


@pytest.fixture
def forecast_file(tmp_path):
    path = tmp_path / "forecasts.csv"
    pd.DataFrame(
        {"median_ea": [0.04, 0.05, 0.06], "p995_ea": [0.10, 0.11, 0.12]},
        index=pd.Index(["2020-01", "2020-07", "2021-01"], name="month"),
    ).to_csv(path, sep=";")
    return path


def forecast_cfg(forecast_file, stat="median_ea", shocks=(3.0, -1.5)):
    cfg = make_cfg()
    cfg["inflation_scenarios"] |= {
        "source": "forecast",
        "forecast_file": str(forecast_file),
        "forecast_stat": stat,
        "high_shock_pp": shocks[0],
        "low_shock_pp": shocks[1],
    }
    return cfg


def history(month):
    index = pd.period_range(end=month, periods=8, freq="M")
    return pd.Series(100.0 * 1.01 ** np.arange(8), index=index)


class TestForecastBase:
    def test_picks_the_decision_month_and_statistic(self, forecast_file):
        assert forecast_base(forecast_cfg(forecast_file), history("2020-07")) == pytest.approx(0.05)
        assert forecast_base(forecast_cfg(forecast_file, "p995_ea"), history("2020-07")) == pytest.approx(
            0.11
        )

    def test_missing_month_raises(self, forecast_file):
        with pytest.raises(ValueError, match="2020-02"):
            forecast_base(forecast_cfg(forecast_file), history("2020-02"))

    def test_unknown_statistic_raises(self, forecast_file):
        with pytest.raises(ValueError, match="forecast_stat"):
            forecast_base(forecast_cfg(forecast_file, "nope"), history("2020-01"))


class TestScenarios:
    def test_forecast_replaces_only_the_base(self, forecast_file):
        s = scenarios(forecast_cfg(forecast_file), history("2020-01"))
        assert s["base"] == pytest.approx(0.04)
        assert s["high"] == pytest.approx(0.04 + 0.03)
        assert s["low"] == pytest.approx(0.04 - 0.015)

    def test_trailing_source_is_unchanged(self, forecast_file):
        cfg = forecast_cfg(forecast_file)
        cfg["inflation_scenarios"]["source"] = "trailing"
        s = scenarios(cfg, history("2020-01"))
        assert s["base"] == pytest.approx(1.01**12 - 1)

    def test_default_source_is_trailing(self):
        cfg = make_cfg()  # no `source` key
        assert scenarios(cfg, history("2020-01"))["base"] == pytest.approx(1.01**12 - 1)


class TestPadUvrHistory:
    def test_prepends_uvr_only_rows_and_keeps_the_panel(self):
        cfg = make_cfg()
        panel = make_panel(cfg, uvr=list(100.0 * 1.005 ** np.arange(13)))
        earlier = pd.Series(
            np.linspace(50.0, 90.0, 40), index=pd.period_range("2016-01", periods=40, freq="M")
        )
        padded = pad_uvr_history(panel, earlier, months=6)
        first = panel.index[0]
        assert len(padded) == len(panel) + 6
        assert padded.index[0] == first - 6
        assert (
            padded.loc[first - 6 : first - 1, "uvr_cop"].tolist()
            == earlier.loc[first - 6 : first - 1].tolist()
        )
        assert padded.loc[first - 6 : first - 1].drop(columns="uvr_cop").isna().all().all()
        pd.testing.assert_frame_equal(padded.loc[first:], panel)

    def test_not_enough_uvr_history_raises(self):
        cfg = make_cfg()
        panel = make_panel(cfg)
        short = pd.Series([90.0], index=pd.period_range(panel.index[0] - 1, periods=1, freq="M"))
        with pytest.raises(ValueError, match="UVR"):
            pad_uvr_history(panel, short, months=6)


class TestForecastRuns:
    def test_case_cfg_overrides_without_mutating(self, forecast_file):
        cfg = forecast_cfg(forecast_file)
        original = copy.deepcopy(cfg)
        out = case_cfg(cfg, "p995", t0="2020-07")
        assert cfg == original
        assert out["backtest"]["t0"] == "2020-07"
        assert out["inflation_scenarios"]["source"] == "forecast"
        assert out["inflation_scenarios"]["forecast_stat"] == "p995_ea"
        assert case_cfg(cfg, "trailing")["inflation_scenarios"]["source"] == "trailing"

    def test_cases(self):
        assert list(CASES) == ["trailing", "median", "p995"]

    def test_base_inflation_log_columns(self, forecast_file):
        cfg = forecast_cfg(forecast_file)
        panel = make_panel(cfg, uvr=list(100.0 * 1.005 ** np.arange(13)))
        log = base_inflation_log(panel, cfg)
        assert list(log.columns) == ["base", "realised_next_6m"]
        assert list(log.index) == ["2020-01", "2020-07"]
        assert log.loc["2020-01", "base"] == pytest.approx(0.04)
        assert log.loc["2020-01", "realised_next_6m"] == pytest.approx(1.005**12 - 1)

    def test_run_cases_smoke(self, forecast_file):
        cfg = forecast_cfg(forecast_file)
        cfg["backtest"]["t0"] = "2020-01"
        panel = make_panel(
            cfg, uvr=list(100.0 * 1.005 ** np.arange(13)), fic=0.05, cdt_180=0.06, cdt_90=0.05, cdt_360=0.07
        )
        results = run_cases(panel, make_schedule({m: 1.0 for m in range(7, 13)}), cfg, t0="2020-01")
        assert set(results) == set(CASES)
        for case in CASES:
            assert {"conservative", "ldi"} <= set(results[case]["summary"].columns)
            assert np.isfinite(results[case]["summary"].to_numpy(dtype=float)).all()

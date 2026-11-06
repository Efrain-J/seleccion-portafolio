import copy

import numpy as np
import pandas as pd
import pytest
from helpers import make_cfg, make_panel, make_schedule

from uvr_loan.config import RESULTS_DIR
from uvr_loan.forecast_runs import CASES, base_inflation_log, case_cfg, output_dir, pad_uvr_history, run_cases
from uvr_loan.inflation import forecast_scenarios, scenarios


def test_output_dir_depends_on_the_decision_scenario():
    assert output_dir(None) == RESULTS_DIR / "forecast_runs"
    assert output_dir("base") == RESULTS_DIR / "forecast_runs_base"


@pytest.fixture
def forecast_file(tmp_path):
    path = tmp_path / "forecasts.csv"
    pd.DataFrame(
        {
            "p05_ea": [0.01, 0.02, 0.03],
            "median_ea": [0.04, 0.05, 0.06],
            "p995_ea": [0.10, 0.11, 0.12],
        },
        index=pd.Index(["2020-01", "2020-07", "2021-01"], name="month"),
    ).to_csv(path, sep=";")
    return path


def forecast_cfg(forecast_file, columns=None):
    cfg = make_cfg()
    cfg["inflation_scenarios"] |= {
        "source": "forecast",
        "forecast_file": str(forecast_file),
        "forecast_columns": columns or {"low": "p05_ea", "base": "median_ea", "high": "p995_ea"},
        "high_shock_pp": 3.0,  # only the trailing source uses the shocks
        "low_shock_pp": -1.5,
    }
    return cfg


def history(month):
    index = pd.period_range(end=month, periods=8, freq="M")
    return pd.Series(100.0 * 1.01 ** np.arange(8), index=index)


class TestForecastScenarios:
    def test_each_scenario_is_a_column_of_the_decision_month(self, forecast_file):
        s = forecast_scenarios(forecast_cfg(forecast_file), history("2020-07"))
        assert s == pytest.approx({"low": 0.02, "base": 0.05, "high": 0.11})

    def test_columns_are_configurable(self, forecast_file):
        cfg = forecast_cfg(forecast_file, {"low": "median_ea", "base": "median_ea", "high": "p995_ea"})
        assert forecast_scenarios(cfg, history("2020-01")) == pytest.approx(
            {"low": 0.04, "base": 0.04, "high": 0.10}
        )

    def test_missing_month_raises(self, forecast_file):
        with pytest.raises(ValueError, match="2020-02"):
            forecast_scenarios(forecast_cfg(forecast_file), history("2020-02"))

    def test_unknown_column_raises(self, forecast_file):
        cfg = forecast_cfg(forecast_file, {"low": "nope", "base": "median_ea", "high": "p995_ea"})
        with pytest.raises(ValueError, match="nope"):
            forecast_scenarios(cfg, history("2020-01"))


class TestScenarios:
    def test_forecast_source_uses_the_distribution_and_no_shocks(self, forecast_file):
        s = scenarios(forecast_cfg(forecast_file), history("2020-01"))
        assert s == pytest.approx({"low": 0.01, "base": 0.04, "high": 0.10})

    def test_trailing_source_adds_the_shocks_to_the_trailing_inflation(self, forecast_file):
        cfg = forecast_cfg(forecast_file)
        cfg["inflation_scenarios"]["source"] = "trailing"
        s = scenarios(cfg, history("2020-01"))
        assert s["base"] == pytest.approx(1.01**12 - 1)
        assert s["high"] == pytest.approx(1.01**12 - 1 + 0.03)
        assert s["low"] == pytest.approx(1.01**12 - 1 - 0.015)

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
    def test_cases(self):
        assert list(CASES) == ["trailing", "forecast"]

    def test_case_cfg_overrides_without_mutating(self, forecast_file):
        cfg = forecast_cfg(forecast_file)
        cfg["inflation_scenarios"]["source"] = "trailing"
        original = copy.deepcopy(cfg)
        out = case_cfg(cfg, "forecast", t0="2020-07")
        assert cfg == original
        assert out["backtest"]["t0"] == "2020-07"
        assert out["inflation_scenarios"]["source"] == "forecast"
        assert (
            case_cfg(forecast_cfg(forecast_file), "trailing")["inflation_scenarios"]["source"] == "trailing"
        )

    def test_decision_scenario_sets_the_scenario_of_every_plan(self, forecast_file):
        cfg = forecast_cfg(forecast_file)
        cfg["conservative"]["fic_sizing_scenario"] = "high"
        cfg["cdt_ladder"]["deflator_scenario"] = "high"
        cfg["ldi"]["floor_scenario"] = "high"
        original = copy.deepcopy(cfg)
        out = case_cfg(cfg, "forecast", decision_scenario="base")
        assert cfg == original
        assert out["conservative"]["fic_sizing_scenario"] == "base"
        assert out["cdt_ladder"]["deflator_scenario"] == "base"
        assert out["ldi"]["floor_scenario"] == "base"
        assert case_cfg(cfg, "forecast")["ldi"]["floor_scenario"] == "high"  # unchanged by default

    def test_unknown_decision_scenario_raises(self, forecast_file):
        with pytest.raises(ValueError, match="decision_scenario"):
            case_cfg(forecast_cfg(forecast_file), "forecast", decision_scenario="medium")

    def test_inflation_log_has_the_three_scenarios_and_the_realized_inflation(self, forecast_file):
        cfg = forecast_cfg(forecast_file)
        panel = make_panel(cfg, uvr=list(100.0 * 1.005 ** np.arange(13)))
        log = base_inflation_log(panel, cfg)
        assert list(log.columns) == ["low", "base", "high", "realised_next_6m"]
        assert list(log.index) == ["2020-01", "2020-07"]
        assert log.loc["2020-01", ["low", "base", "high"]].tolist() == pytest.approx([0.01, 0.04, 0.10])
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

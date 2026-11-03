from unittest.mock import Mock

import pandas as pd
import pytest

from uvr_loan.data.cleaning import build_monthly_panel, to_month_end
from uvr_loan.data.sources import cached, fetch_banrep_series, fetch_yahoo_close


def test_to_month_end_takes_last_value():
    s = pd.Series([1.0, 2.0, 3.0], index=pd.to_datetime(["2020-01-03", "2020-01-30", "2020-02-14"]))
    result = to_month_end(s)
    assert list(result) == [2.0, 3.0]
    assert list(result.index) == [pd.Period("2020-01", "M"), pd.Period("2020-02", "M")]


def test_panel_converts_rates_to_decimals():
    idx = pd.to_datetime(["2020-01-31", "2020-02-28"])
    raw = {"uvr": pd.Series([270.0, 271.0], idx), "cdt_180": pd.Series([5.0, 6.0], idx)}
    panel = build_monthly_panel(raw, rate_columns=["cdt_180"], start="2020-01", end="2020-02")
    assert list(panel["cdt_180"]) == [0.05, 0.06]
    assert list(panel["uvr"]) == [270.0, 271.0]


def test_panel_detects_gaps():
    raw = {"uvr": pd.Series([270.0, 272.0], pd.to_datetime(["2020-01-31", "2020-03-31"]))}
    with pytest.raises(ValueError, match="2020-02"):
        build_monthly_panel(raw, rate_columns=[], start="2020-01", end="2020-03")


def test_cache_skips_download_when_file_exists(tmp_path):
    s = pd.Series([1.0, 2.0], pd.to_datetime(["2020-01-01", "2020-01-02"]), name="value")
    fetch = Mock(return_value=s)
    path = tmp_path / "series.csv"

    first = cached(path, fetch)
    second = cached(path, fetch)

    fetch.assert_called_once()
    pd.testing.assert_series_equal(first, second, check_freq=False)


@pytest.mark.network
def test_download_icolcap_has_prices_in_t0():
    close = fetch_yahoo_close("ICOLCAP.CL", "2016-10-01", "2016-11-01")
    assert len(close) > 15
    assert (close > 0).all()


@pytest.mark.network
def test_download_uvr_from_banrep():
    uvr = fetch_banrep_series(850)
    assert uvr["2016-10-01"] == pytest.approx(242.9438)

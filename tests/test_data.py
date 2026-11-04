from unittest.mock import Mock

import pandas as pd
import pytest

from uvr_loan.data import sources
from uvr_loan.data.cleaning import build_fic_index, build_monthly_panel, fic_returns, to_month_end
from uvr_loan.data.sources import (
    cached,
    cached_table,
    fetch_banrep_series,
    fetch_money_market_fic,
    fetch_socrata,
    fetch_yahoo_close,
)


def test_to_month_end_takes_last_value():
    s = pd.Series([1.0, 2.0, 3.0], index=pd.to_datetime(["2020-01-03", "2020-01-30", "2020-02-14"]))
    result = to_month_end(s)
    assert list(result) == [2.0, 3.0]
    assert list(result.index) == [pd.Period("2020-01", "M"), pd.Period("2020-02", "M")]


def test_panel_converts_rates_to_decimals():
    idx = pd.to_datetime(["2020-01-31", "2020-02-28"])
    raw = {"uvr_cop": pd.Series([270.0, 271.0], idx), "cdt_180d_ea": pd.Series([5.0, 6.0], idx)}
    panel = build_monthly_panel(raw, pct_columns=["cdt_180d_ea"], start="2020-01", end="2020-02")
    assert list(panel["cdt_180d_ea"]) == [0.05, 0.06]
    assert list(panel["uvr_cop"]) == [270.0, 271.0]


def test_panel_detects_gaps():
    raw = {"uvr_cop": pd.Series([270.0, 272.0], pd.to_datetime(["2020-01-31", "2020-03-31"]))}
    with pytest.raises(ValueError, match="2020-02"):
        build_monthly_panel(raw, pct_columns=[], start="2020-01", end="2020-03")


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


# FIC index built from the Superfinanciera daily reports of money market funds.


def funds(rows):
    """rows: (date, fund code, unit value, fund size)."""
    return pd.DataFrame(
        {
            "fecha_corte": pd.to_datetime([r[0] for r in rows]),
            "codigo_entidad": 1,
            "codigo_negocio": [r[1] for r in rows],
            "tipo_participacion": 800,
            "valor_unidad_operaciones": [r[2] for r in rows],
            "valor_fondo_cierre_dia_t": [r[3] for r in rows],
        }
    )


def test_fic_index_weights_by_the_size_of_the_previous_day():
    data = funds(
        [
            ("2020-01-01", 10, 100.0, 100.0),
            ("2020-01-02", 10, 101.0, 999.0),  # +1 %, weight 100 (size of the previous day)
            ("2020-01-01", 20, 50.0, 300.0),
            ("2020-01-02", 20, 51.5, 1.0),  # +3 %, weight 300
        ]
    )
    level = build_fic_index(data, max_daily_change=0.05)
    assert level["2020-01-02"] == pytest.approx(1.025)


def test_fic_index_only_counts_a_fund_on_the_days_it_reports():
    data = funds(
        [
            ("2020-01-01", 10, 100.0, 100.0),
            ("2020-01-02", 10, 101.0, 100.0),
            ("2020-01-03", 10, 102.01, 100.0),
            ("2020-01-02", 20, 50.0, 100.0),  # appears on day 2: its first return is on day 3
            ("2020-01-03", 20, 51.5, 100.0),
        ]
    )
    level = build_fic_index(data, max_daily_change=0.05)
    assert level["2020-01-02"] == pytest.approx(1.01)
    assert level["2020-01-03"] == pytest.approx(1.01 * 1.02)


def test_fic_index_logs_and_excludes_zero_unit_values(caplog):
    data = funds(
        [
            ("2020-01-01", 10, 100.0, 100.0),
            ("2020-01-02", 10, 0.0, 100.0),
            ("2020-01-01", 20, 100.0, 100.0),
            ("2020-01-02", 20, 101.0, 100.0),
        ]
    )
    with caplog.at_level("WARNING"):
        level = build_fic_index(data, max_daily_change=0.05)
    assert level["2020-01-02"] == pytest.approx(1.01)
    assert "unit value <= 0" in caplog.text
    assert "fund 1-10-800 on 2020-01-02" in caplog.text


def test_fic_index_logs_and_excludes_jumps_above_the_limit(caplog):
    data = funds(
        [
            ("2020-01-01", 10, 100.0, 100.0),
            ("2020-01-02", 10, 106.0, 100.0),  # +6 % in one day
            ("2020-01-01", 20, 100.0, 100.0),
            ("2020-01-02", 20, 101.0, 100.0),
        ]
    )
    with caplog.at_level("WARNING"):
        level = build_fic_index(data, max_daily_change=0.05)
    assert level["2020-01-02"] == pytest.approx(1.01)
    assert "daily change above 5%" in caplog.text
    assert "+6.00%" in caplog.text


def test_fic_index_logs_and_drops_duplicated_rows(caplog):
    data = funds(
        [("2020-01-01", 10, 100.0, 100.0), ("2020-01-01", 10, 100.0, 100.0), ("2020-01-02", 10, 101.0, 100.0)]
    )
    with caplog.at_level("WARNING"):
        level = build_fic_index(data, max_daily_change=0.05)
    assert level["2020-01-02"] == pytest.approx(1.01)
    assert "1 duplicated" in caplog.text


def test_fic_returns_monthly_return_and_known_annual_rate():
    level = pd.Series([1.0, 1.01, 1.0302], index=pd.period_range("2020-01", periods=3, freq="M"))
    rates = fic_returns(level)
    assert rates["fic_ret_m"].iloc[1:].tolist() == pytest.approx([0.01, 0.02])
    assert rates.loc[pd.Period("2020-03", "M"), "fic_rate_ea"] == pytest.approx(1.02**12 - 1)


def test_socrata_pages_until_a_short_page(monkeypatch):
    pages = [[{"a": 1}, {"a": 2}], [{"a": 3}]]
    calls = []

    def fake_get(url):
        calls.append(url)
        return pages[len(calls) - 1]

    monkeypatch.setattr(sources, "_get_json", fake_get)
    table = fetch_socrata("abcd-1234", {"$where": "x=1"}, page_size=2)
    assert table["a"].tolist() == [1, 2, 3]
    assert len(calls) == 2
    assert "%24offset=2" in calls[1]


def test_cached_table_skips_download_when_file_exists(tmp_path):
    table = funds([("2020-01-01", 10, 100.0, 100.0)])
    fetch = Mock(return_value=table)
    first = cached_table(tmp_path / "t.csv", fetch)
    second = cached_table(tmp_path / "t.csv", fetch)
    fetch.assert_called_once()
    pd.testing.assert_frame_equal(first, second)
    assert first["fecha_corte"].dtype.kind == "M"


@pytest.mark.network
def test_download_money_market_fic_has_funds_in_t0():
    table = fetch_money_market_fic("qhpu-8ixx", "FIC DE MERCADO MONETARIO", "2016-10-31", "2016-10-31")
    assert len(table) >= 10
    assert (table["valor_unidad_operaciones"] > 0).all()

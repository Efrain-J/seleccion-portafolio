from unittest.mock import Mock

import numpy as np
import pandas as pd
import pytest

from uvr_loan.data import sources
from uvr_loan.data.cleaning import (
    build_fic_index,
    build_monthly_panel,
    etf_columns,
    fic_returns,
    to_month_end,
)
from uvr_loan.data.sources import (
    cached,
    cached_table,
    fetch_banrep_series,
    fetch_money_market_fic,
    fetch_socrata,
    fetch_yahoo_close,
    load_uvr,
)


def test_load_uvr_reads_only_the_uvr_cache(monkeypatch, tmp_path):
    """The UVR comes from its own cache file; the other series (CDT, TRM) are never requested."""
    dates = pd.DatetimeIndex(["2020-01-01", "2020-01-02"], name="date")
    s = pd.Series([270.0, 271.0], dates, name="value")
    s.to_csv(tmp_path / "banrep_850.csv")
    monkeypatch.setattr(sources, "RAW_DIR", tmp_path)
    monkeypatch.setattr(sources, "fetch_banrep_series", Mock(side_effect=AssertionError("no download expected")))
    result = load_uvr({"data": {"uvr_series": 850}})
    pd.testing.assert_series_equal(result, s, check_freq=False)


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


def test_etf_columns_convert_usd_with_the_trm_of_the_same_month_and_use_past_volatility():
    days = pd.to_datetime(["2020-01-15", "2020-01-31", "2020-02-28", "2020-03-31"])
    usd = pd.Series([9.0, 10.0, 11.0, 9.9], days)
    trm = pd.Series([3_000.0, 4_000.0, 4_000.0, 5_000.0], days)
    cols = etf_columns(
        {"cspx": usd, "icolcap": usd * 1_000}, {"cspx": "USD", "icolcap": "COP"}, trm, window=2, trend_window=2
    )
    assert list(cols["cspx_price_cop"]) == pytest.approx([40_000.0, 44_000.0, 49_500.0])
    assert list(cols["icolcap_price_cop"]) == pytest.approx([10_000.0, 11_000.0, 9_900.0])
    returns = pd.Series([0.10, 0.125])  # COP returns of cspx in February and March
    assert cols["cspx_vol_ea"].iloc[-1] == pytest.approx(returns.std() * 12**0.5)
    assert cols["cspx_vol_ea"].iloc[:2].isna().all()  # needs `window` returns
    assert cols["cspx_trend_ret"].iloc[-1] == pytest.approx(49_500.0 / 40_000.0 - 1)  # last `trend_window` months
    assert cols["cspx_trend_ret"].iloc[:2].isna().all()


def test_etf_columns_reject_an_unknown_currency():
    s = pd.Series([1.0], pd.to_datetime(["2020-01-31"]))
    with pytest.raises(ValueError, match="EUR"):
        etf_columns({"x": s}, {"x": "EUR"}, s, window=2, trend_window=2)


def test_etf_cache_file_includes_the_start_date(monkeypatch, tmp_path):
    """A cache downloaded with another start date must not be reused, so the start is in the file name."""
    calls = []

    def fake_fetch(ticker, start, end):
        calls.append((ticker, start, end))
        return pd.Series([1.0, 2.0], pd.to_datetime(["2013-01-02", "2013-01-03"]), name="value")

    monkeypatch.setattr(sources, "RAW_DIR", tmp_path)
    monkeypatch.setattr(sources, "fetch_yahoo_close", fake_fetch)
    cfg = {
        "data": {
            "etf_history_start": "2013-01-01",
            "end": "2026-11-30",
            "etfs": {"cspx": {"ticker": "CSPX.L", "currency": "USD"}},
        }
    }
    prices = sources.load_etf_prices(cfg)
    assert (tmp_path / "yahoo_CSPX.L_2013-01-01.csv").exists()
    assert calls == [("CSPX.L", "2013-01-01", "2026-11-30")]
    assert list(prices["cspx"]) == [1.0, 2.0]


def test_etf_columns_only_use_data_up_to_each_month():
    """Changing prices and TRM after a cut must not change the price or volatility of any month up to the cut."""
    days = pd.date_range("2013-01-31", periods=60, freq="ME")
    rng = np.random.default_rng(0)
    usd = pd.Series(100 * np.cumprod(1 + rng.normal(0, 0.04, 60)), days)
    trm = pd.Series(3_000 * np.cumprod(1 + rng.normal(0, 0.02, 60)), days)
    cut = days[40]
    later = days > cut
    usd_bad, trm_bad = usd.copy(), trm.copy()
    usd_bad[later] *= 5.0
    trm_bad[later] *= 0.2

    def build(price, rate):
        return etf_columns({"cspx": price}, {"cspx": "USD"}, rate, window=12, trend_window=12)

    base, bad = build(usd, trm), build(usd_bad, trm_bad)
    month = cut.to_period("M")
    pd.testing.assert_frame_equal(base.loc[:month], bad.loc[:month], check_exact=True)
    assert not base.loc[month + 1 :].equals(bad.loc[month + 1 :])

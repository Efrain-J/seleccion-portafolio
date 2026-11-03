"""Download of raw series with a CSV cache in data/raw/.

- BanRep SUAMECA: UVR and CDT/DTF rates, by series ID (see `data` in assumptions.yaml).
- Yahoo Finance: ETF prices (adjusted close, so dividends are included).

Run `python -m uvr_loan.data.sources` to download every series in the config.
"""

import json
import ssl
import urllib.request
from collections.abc import Callable
from functools import partial
from pathlib import Path
from typing import Any

import pandas as pd
import truststore
import yfinance as yf

from uvr_loan.config import ROOT, load_assumptions

RAW_DIR = ROOT / "data" / "raw"
SUAMECA_URL = (
    "https://suameca.banrep.gov.co/estadisticas-economicas-back/rest/"
    "estadisticaEconomicaRestService/consultaInformacionSerie"
)


def fetch_banrep_series(series_id: int) -> pd.Series:
    """Full history of a SUAMECA series, indexed by date.

    Uses the OS certificate store (truststore): the BanRep server does not send its
    intermediate certificate, so the default Python bundle fails to verify it.
    """
    request = urllib.request.Request(
        f"{SUAMECA_URL}?idSerie={series_id}", headers={"User-Agent": "Mozilla/5.0"}
    )
    context = truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    with urllib.request.urlopen(request, context=context, timeout=120) as response:
        data = json.load(response)[0]["data"]  # [[epoch_ms, value], ...]
    dates = pd.to_datetime([ms for ms, _ in data], unit="ms").normalize()
    return pd.Series([v for _, v in data], index=dates, name="value")


def fetch_yahoo_close(ticker: str, start: str, end: str) -> pd.Series:
    """Daily adjusted close price between `start` and `end`."""
    close = yf.Ticker(ticker).history(start=start, end=end, auto_adjust=True)["Close"]
    close.index = close.index.tz_localize(None).normalize()
    return close.rename("value")


def cached(path: Path, fetch: Callable[[], pd.Series]) -> pd.Series:
    """Read the series from `path`; download it with `fetch` only if the file does not exist."""
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        fetch().to_csv(path, index_label="date")
    return pd.read_csv(path, index_col="date", parse_dates=True)["value"]


def load_raw(cfg: dict[str, Any]) -> dict[str, pd.Series]:
    """Every raw series in the config, by column name (uvr, rates, etf)."""
    data = cfg["data"]
    banrep = {"uvr": data["uvr_series"], **data["rate_series"]}
    raw = {
        name: cached(RAW_DIR / f"banrep_{series_id}.csv", partial(fetch_banrep_series, series_id))
        for name, series_id in banrep.items()
    }
    ticker = data["etf_ticker"]
    raw["etf"] = cached(
        RAW_DIR / f"yahoo_{ticker}.csv", partial(fetch_yahoo_close, ticker, data["start"], data["end"])
    )
    return raw


if __name__ == "__main__":
    for name, s in load_raw(load_assumptions()).items():
        print(f"{name:<8} {len(s):>6} rows  {s.index.min():%Y-%m-%d} -> {s.index.max():%Y-%m-%d}")

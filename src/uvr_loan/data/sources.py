"""Download of raw series with a CSV cache in data/raw/.

- BanRep SUAMECA: UVR and CDT/DTF rates, by series ID (see `data` in assumptions.yaml).
- Yahoo Finance: ETF prices (adjusted close, so dividends are included).
- Superfinanciera (datos.gov.co): daily unit values of the money market FICs.

Run `python -m uvr_loan.data.sources` to download every series in the config.
"""

import json
import logging
import ssl
import urllib.parse
import urllib.request
from collections.abc import Callable
from functools import partial
from pathlib import Path
from typing import Any

import pandas as pd
import truststore
import yfinance as yf

from uvr_loan.config import ROOT, load_assumptions

log = logging.getLogger(__name__)

RAW_DIR = ROOT / "data" / "raw"
SOCRATA_URL = "https://www.datos.gov.co/resource/{dataset}.json"
FIC_COLUMNS = [
    "fecha_corte",
    "codigo_entidad",
    "codigo_negocio",
    "tipo_participacion",
    "valor_unidad_operaciones",
    "valor_fondo_cierre_dia_t",
]
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


def _get_json(url: str) -> Any:
    context = truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    with urllib.request.urlopen(url, context=context, timeout=300) as response:
        return json.load(response)


def fetch_socrata(dataset: str, query: dict[str, str], page_size: int = 50_000) -> pd.DataFrame:
    """Every row of a datos.gov.co (Socrata) query, requested in pages until a page comes back short.

    `query` holds the SoQL parameters ($select, $where, ...); it must include an $order so that
    the pages do not repeat or skip rows.
    """
    rows: list[dict[str, Any]] = []
    while True:
        params = {**query, "$limit": page_size, "$offset": len(rows)}
        page = _get_json(f"{SOCRATA_URL.format(dataset=dataset)}?{urllib.parse.urlencode(params)}")
        rows += page
        log.info("%s: %d rows downloaded", dataset, len(rows))
        if len(page) < page_size:
            return pd.DataFrame(rows)


def fetch_money_market_fic(dataset: str, subtype: str, start: str, end: str) -> pd.DataFrame:
    """Daily report (unit value and size) of every fund of `subtype`, main compartment only."""
    where = (
        f"nombre_subtipo_patrimonio = '{subtype}' AND principal_compartimento = 1 "
        f"AND fecha_corte between '{start}T00:00:00' and '{end}T00:00:00'"
    )
    query = {"$select": ",".join(FIC_COLUMNS), "$where": where, "$order": ",".join(FIC_COLUMNS[:4])}
    table = fetch_socrata(dataset, query)
    table["fecha_corte"] = pd.to_datetime(table["fecha_corte"])
    return table.astype({col: float for col in FIC_COLUMNS[1:]})


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


def cached_table(path: Path, fetch: Callable[[], pd.DataFrame]) -> pd.DataFrame:
    """Same as `cached`, for a table with a `fecha_corte` date column."""
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        fetch().to_csv(path, index=False)
    return pd.read_csv(path, parse_dates=["fecha_corte"])


def load_fic_funds(cfg: dict[str, Any]) -> pd.DataFrame:
    """Daily reports of the money market FICs between `data.start` and `data.end`."""
    data, funds = cfg["data"], cfg["data"]["fic_source"]
    fetch = partial(fetch_money_market_fic, funds["dataset"], funds["subtype"], data["start"], data["end"])
    return cached_table(RAW_DIR / f"sfc_{funds['dataset']}_money_market.csv", fetch)


def load_raw(cfg: dict[str, Any]) -> dict[str, pd.Series]:
    """Every raw series in the config, by panel column name (UVR, CDT rates, ETF price)."""
    data = cfg["data"]
    banrep = {"uvr_cop": data["uvr_series"], **data["cdt_series"]}
    raw = {
        name: cached(RAW_DIR / f"banrep_{series_id}.csv", partial(fetch_banrep_series, series_id))
        for name, series_id in banrep.items()
    }
    ticker = data["etf_ticker"]
    raw["etf_price_cop"] = cached(
        RAW_DIR / f"yahoo_{ticker}.csv", partial(fetch_yahoo_close, ticker, data["start"], data["end"])
    )
    return raw


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    cfg = load_assumptions()
    for name, s in load_raw(cfg).items():
        print(f"{name:<8} {len(s):>6} rows  {s.index.min():%Y-%m-%d} -> {s.index.max():%Y-%m-%d}")
    funds = load_fic_funds(cfg)
    print(
        f"fic      {len(funds):>6} rows  {funds['fecha_corte'].min():%Y-%m-%d} -> {funds['fecha_corte'].max():%Y-%m-%d}"
    )

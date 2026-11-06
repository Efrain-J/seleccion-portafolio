"""Monthly data panel (end of month) built from the raw series.

Run `python -m uvr_loan.data.cleaning` to write data/processed/monthly_panel.csv.
"""

import logging
from collections.abc import Iterable
from typing import Any

import pandas as pd

from uvr_loan.config import ROOT, load_assumptions
from uvr_loan.data.sources import load_etf_prices, load_fic_funds, load_raw

log = logging.getLogger(__name__)

PANEL_PATH = ROOT / "data" / "processed" / "monthly_panel.csv"
FUND_KEY = ["codigo_entidad", "codigo_negocio", "tipo_participacion"]


def to_month_end(s: pd.Series) -> pd.Series:
    """Last available value of each calendar month, indexed by monthly period."""
    return s.groupby(s.index.to_period("M")).last()


def build_monthly_panel(
    raw: dict[str, pd.Series], pct_columns: Iterable[str], start: str, end: str
) -> pd.DataFrame:
    """One row per month between `start` and `end`; the `pct_columns` go from % to decimals.

    Raises ValueError if any month is missing a value.
    """
    months = pd.period_range(start, end, freq="M")
    panel = pd.DataFrame({name: to_month_end(s) for name, s in raw.items()}).reindex(months)
    for col in pct_columns:
        panel[col] = panel[col] / 100
    check_complete(panel)
    return panel


def check_complete(panel: pd.DataFrame) -> None:
    """Raise ValueError naming the months with a missing value."""
    missing = panel[panel.isna().any(axis=1)]
    if not missing.empty:
        raise ValueError(f"Missing data in months: {', '.join(str(m) for m in missing.index)}")


def etf_columns(
    prices: dict[str, pd.Series], currencies: dict[str, str], trm: pd.Series, window: int
) -> pd.DataFrame:
    """Monthly `<name>_price_cop` and `<name>_vol_ea` of each ETF, indexed by monthly period.

    `prices` are daily closes in each ETF's currency (COP or USD) and `trm` the daily COP per USD;
    both take their month-end value, so a USD price is converted with the TRM of the same month (S17).
    `<name>_vol_ea` is the standard deviation of the last `window` monthly returns in COP, times
    sqrt(12): it only uses months up to its own, so it is known at the close of that month.
    """
    trm_m = to_month_end(trm)
    columns = {}
    for name, price in prices.items():
        price_m = to_month_end(price)
        if currencies[name] == "USD":
            price_m = price_m * trm_m.reindex(price_m.index)
        elif currencies[name] != "COP":
            raise ValueError(f"Unsupported currency for {name}: {currencies[name]}")
        columns[f"{name}_price_cop"] = price_m
        columns[f"{name}_vol_ea"] = price_m.pct_change().rolling(window).std() * 12**0.5
    return pd.DataFrame(columns)


def _log_rows(rows: pd.DataFrame, reason: str) -> None:
    log.warning("%d fund-days excluded from the FIC index: %s", len(rows), reason)
    for row in rows.itertuples():
        log.warning(
            "  fund %d-%d-%d on %s: unit value %s -> %s (%+.2f%%)",
            row.codigo_entidad,
            row.codigo_negocio,
            row.tipo_participacion,
            f"{row.fecha_corte:%Y-%m-%d}",
            row.prev_unit,
            row.valor_unidad_operaciones,
            100 * row.ret,
        )


def build_fic_index(funds: pd.DataFrame, max_daily_change: float) -> pd.Series:
    """Daily level of an index of real funds, starting at 1.

    Each day the index moves with the average return of the funds that report that day and
    the previous time, weighted by each fund's size the previous time. Days with a unit value
    <= 0 or a change above `max_daily_change` are excluded and logged, as are duplicated rows.
    """
    duplicated = funds.duplicated(FUND_KEY + ["fecha_corte"])
    if duplicated.any():
        log.warning("%d duplicated fund-day rows dropped from the FIC data", duplicated.sum())
    funds = funds[~duplicated].sort_values(FUND_KEY + ["fecha_corte"])

    previous = funds.groupby(FUND_KEY)[["valor_unidad_operaciones", "valor_fondo_cierre_dia_t"]].shift()
    funds = funds.assign(
        prev_unit=previous["valor_unidad_operaciones"],
        weight=previous["valor_fondo_cierre_dia_t"],
    )
    funds = funds[funds["prev_unit"].notna()]
    funds = funds.assign(ret=funds["valor_unidad_operaciones"] / funds["prev_unit"] - 1)

    zero = (funds["valor_unidad_operaciones"] <= 0) | (funds["prev_unit"] <= 0)
    jump = ~zero & (funds["ret"].abs() > max_daily_change)
    if zero.any():
        _log_rows(funds[zero], "unit value <= 0")
    if jump.any():
        _log_rows(funds[jump], f"daily change above {max_daily_change:.0%}")

    valid = funds[~zero & ~jump & (funds["weight"] > 0)]
    weighted = (valid["ret"] * valid["weight"]).groupby(valid["fecha_corte"]).sum()
    daily = weighted / valid["weight"].groupby(valid["fecha_corte"]).sum()
    return (1 + daily).cumprod().rename("value")


def fic_returns(level: pd.Series) -> pd.DataFrame:
    """From the month-end level of the FIC index: `fic_ret_m`, the return realized during each
    month (moves the money), and `fic_rate_ea`, that return annualized, known at the close of the
    month (used for decisions)."""
    monthly = level.pct_change()
    return pd.DataFrame({"fic_ret_m": monthly, "fic_rate_ea": (1 + monthly) ** 12 - 1})


def load_monthly_panel(cfg: dict[str, Any]) -> pd.DataFrame:
    """Panel from `data.start` up to the last month of the horizon."""
    data = cfg["data"]
    end = pd.Period(cfg["backtest"]["t0"], "M") + cfg["backtest"]["horizon_months"]
    raw = load_raw(cfg)
    raw["fic_index"] = build_fic_index(load_fic_funds(cfg), data["fic_source"]["max_daily_change"])
    panel = build_monthly_panel(raw, data["cdt_series"], data["start"][:7], str(end))
    currencies = {name: etf["currency"] for name, etf in data["etfs"].items()}
    etfs = etf_columns(load_etf_prices(cfg), currencies, raw["trm_cop"], data["vol_window_months"])
    panel = panel.join(fic_returns(panel["fic_index"])).join(etfs)
    # The FIC returns start one month after the panel and the volatilities need `data.vol_window_months`
    # of history (ICOLCAP starts in May 2013): the ETF prices are checked in every month, and every
    # column from t0 on.
    prices = [c for c in etfs.columns if c.endswith("_price_cop")]
    check_complete(panel[prices])
    check_complete(panel.loc[cfg["backtest"]["t0"] :])
    return panel


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    panel = load_monthly_panel(load_assumptions())
    PANEL_PATH.parent.mkdir(parents=True, exist_ok=True)
    panel.to_csv(PANEL_PATH, index_label="month")
    print(panel.loc["2016-10":"2016-12"])
    print(f"{len(panel)} months written to {PANEL_PATH}")


if __name__ == "__main__":
    main()

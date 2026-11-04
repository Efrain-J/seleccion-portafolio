# Data sources

Series used by the model, where they come from and how they are used. Downloaded on 2026-11-03 (the TRM and the ETFs
from 2013 on 2026-11-04) with
`python -m uvr_loan.data.sources` (code in `src/uvr_loan/data/sources.py`, IDs in `config/assumptions.yaml` under
`data`). The raw files are cached in `data/raw/` and are not versioned.

## Summary

| Series | Panel column | Source | ID / ticker | Unit | Frequency | First date | Raw file |
|---|---|---|---|---|---|---|---|
| UVR | `uvr_cop` | Banco de la República (SUAMECA) | 850 | COP per UVR | Daily | 2000-01-01 | `banrep_850.csv` |
| CDT 180 days | `cdt_180d_ea` | Banco de la República (SUAMECA), with Superfinanciera data | 67 | % effective annual, base 365 | Weekly | 1993-07-16 | `banrep_67.csv` |
| CDT 360 days | `cdt_360d_ea` | Banco de la República (SUAMECA), with Superfinanciera data | 68 | % effective annual, base 365 | Weekly | 1993-07-16 | `banrep_68.csv` |
| DTF 90 days | `cdt_90d_ea` | Banco de la República (SUAMECA), with Superfinanciera data | 65 | % effective annual, base 365 | Weekly | 1984-01-20 | `banrep_65.csv` |
| Money market FICs | `fic_index`, `fic_ret_m`, `fic_rate_ea` | Superintendencia Financiera (datos.gov.co) | `qhpu-8ixx` | Unit value (COP) and fund size per fund and share class | Daily | 2016-01-01 | `sfc_qhpu-8ixx_money_market.csv` |
| TRM | `trm_cop` | Banco de la República (SUAMECA), with Superfinanciera data | 1 | COP per USD | Daily | 1991-11-27 | `banrep_1.csv` |
| iShares COLCAP ETF | `icolcap_price_cop`, `icolcap_vol_ea` | Yahoo Finance | `ICOLCAP.CL` | COP, close adjusted for dividends | Daily (BVC trading days) | 2013-05-02 | `yahoo_ICOLCAP.CL_2013-01-01.csv` |
| iShares Core S&P 500 UCITS ETF (Acc) | `cspx_price_cop`, `cspx_vol_ea` | Yahoo Finance | `CSPX.L` | USD, close adjusted (accumulating fund); converted to COP with the TRM | Daily (LSE trading days) | 2013-01-02 (requested range) | `yahoo_CSPX.L_2013-01-01.csv` |

In the monthly panel (`src/uvr_loan/data/cleaning.py`) every series takes its last value of each calendar month, and
the rates are converted from % to decimals. The ETFs (`data.etfs` in the config) are downloaded from
`data.etf_history_start` (2013), before the rest of the panel, because `<name>_vol_ea` needs 36 months of returns
before t0: it is the standard deviation of the last 36 monthly returns in COP times sqrt(12), using only months up to
its own. A USD price is converted with the month-end TRM of the same month (`etf_columns`). The cache file name of an
ETF includes the start date, so a cache downloaded with another start is not reused.

## Banco de la República – SUAMECA

- Endpoint used (JSON, no authentication):
  `https://suameca.banrep.gov.co/estadisticas-economicas-back/rest/estadisticaEconomicaRestService/consultaInformacionSerie?idSerie=<ID>`
- The response is a list with one object. Its `data` field holds the full history as `[[epoch_ms, value], ...]`; the
  other fields are metadata (name, unit, frequency, source, methodology notes).
- Public page of the UVR series:
  https://suameca.banrep.gov.co/estadisticas-economicas/informacionSerie/100005/unidad_valor_real_uvr
- How the IDs were found: the endpoint is not officially documented. The IDs come from the data catalog that the
  SUAMECA site itself loads:
  `.../estadisticaEconomicaRestService/consultaMenuXopcion?opcion=CATALOGO_DATOS`.
  - Entry "UVR_Unidad de valor real" → series 850.
  - Entry "CDT's a 90 (DTF), 180 y 360 días" → series 65, 67 and 68.
  - Entry "IBR_Indicador Bancario de Referencia" → series 241 (overnight) and others.
- Methodology of the CDT and DTF rates (weighted average of CDT deposits reported by banks to the Superfinanciera,
  formato 441): https://www.banrep.gov.co/sites/default/files/ficha-metodologica-tasas-de-captacion.pdf

### UVR (850)
Value in COP of one UVR, certified by Banco de la República from the CPI. It converts the loan payments from UVR to COP.

### TRM (1)
Tasa Representativa del Mercado: COP per USD, computed by the Superintendencia Financiera from the previous business
day's trades and published by BanRep. It converts the USD price of CSPX to COP (S17).

### CDT 180 days (67)
Weighted average rate of 180-day CDTs. It is the rate of the CDT the conservative plan buys at each review, and of the
6-month CDTs of plan 2.

### CDT 360 days (68)
Weighted average rate of 360-day CDTs. It is the rate of the 12-month CDTs of plan 2.

### DTF 90 days (65)
Weighted average rate of 90-day CDTs. It is the rate of the 3-month CDTs of plan 2.

## Superintendencia Financiera – FIC returns (datos.gov.co)

- Dataset "Rentabilidades de los Fondos de Inversión Colectiva (FIC)", ID `qhpu-8ixx`, API
  `https://www.datos.gov.co/resource/qhpu-8ixx.json` (Socrata, SoQL). Daily report of every fund since 2016-01-01.
- Query used: funds whose subtype that day is `FIC DE MERCADO MONETARIO` (open, sight funds that invest at very short
  term), main compartment only (`principal_compartimento = 1`), from `data.start` to `data.end`, only 6 columns
  (date, entity, fund, share class, unit value, fund size). It returns about 55,000 rows in two pages of 50,000 and
  takes under a minute; the rows are cached in `data/raw/`.
- **Index, not a single fund.** Each day, the return of each fund and share class is the change of its unit value
  (net of the fund's fees); the index moves with the average of the funds that report that day, weighted by each
  one's size the previous time it reported. A fund that closes leaves the index that day and a new one enters, so
  the index uses no future information and does not depend on picking a fund that survived (in Oct 2016 the six
  largest funds were Casa de Bolsa Liquidez, Fiduagraria FIC 600 and Confirenta, BTG Pactual, Davibank 1525 and
  Fiduaval Confianza Plus; only the last three still report in 2026).
- **Data checks** (`build_fic_index` in `cleaning.py`): duplicated fund-day rows are dropped, and fund-days with a unit value
  <= 0 or a daily change above `fic_source.max_daily_change` (5 %) are excluded from the index. Each case is logged
  with the fund, the date and the unit values. In the 2016–2026 download: 8 fund-days with a unit value of 0 and 5
  with jumps above 5 % (out of 54,614 rows).
- Panel columns: `fic_index` (month-end level), `fic_ret_m` (return realized during the month, used for the money)
  and `fic_rate_ea` (that return annualized, known at the close of the month, used for decisions).

## Yahoo Finance

- Ticker `ICOLCAP.CL`: iShares MSCI COLCAP (Fondo Bursátil), listed on the Bolsa de Valores de Colombia, prices in COP.
  On Yahoo its history starts in 2013.
- Downloaded with `yfinance` (`Ticker.history(auto_adjust=True)`). The adjusted close includes dividends, so the price
  change is the total return.
- Do not confuse it with `ICOL` (iShares MSCI Colombia ETF, NYSE Arca, in USD): it tracks a different index and Yahoo
  no longer returns data for it.
- Ticker `CSPX.L`: iShares Core S&P 500 UCITS ETF (Acc), domiciled in Ireland, USD line on the London Stock Exchange,
  launched in 2010. It is accumulating (dividends are reinvested inside the fund), so its price is already the total
  return net of the 15 % US withholding on dividends (Ireland–US treaty) and of its 0.07 % fee. The US-listed `IVV`
  would assume dividends with no withholding, and a Colombian resident pays 30 % on them (no tax treaty).
- Other Irish ETFs checked: `SSAC.L` (MSCI ACWI) and `SWDA.L` (MSCI World) are quoted in GBp on Yahoo, so they would
  need a GBP→USD series; `SWDA.L` also has one daily change of 34 % that looks like a bad print. `VWRA.L` (Vanguard
  FTSE All-World, USD) only starts in Jul-2019.

## Known issues

- **ICOLCAP, Dec-2025:** the month-end close (2025-12-30) is 20,000, −4.7 % from the day before, with the day's low
  equal to the close; the price recovers to 20,480 and 20,994 in the next sessions. It may be a bad print, which would
  understate Dec-2025 and overstate Jan-2026. It could not be confirmed with a second source. Plan 3 holds ICOLCAP, so
  this may affect its Dec-2025 and Jan-2026 values, its volatility and its drawdown; it does not change the following
  months.
- **ICOLCAP, adjusted close:** Yahoo's adjusted close is rescaled back in time with every new dividend (the factor was
  0.658 in Oct-2016 at download time). Returns are consistent, but price levels change if the data is downloaded again;
  the cache in `data/raw/` keeps the results reproducible.
- **ICOLCAP, 2024–2025:** Yahoo has no volume for many days (149 in 2024, 229 in 2025), but the prices are not stale:
  they change from day to day with real open/high/low values.
- **Timing:** the weekly CDT rates are dated on Fridays, so the month-end value is the last Friday of the month (up to
  6 days before the close). FIC unit values are published about one day after their date. The London, Colombian and
  US holidays differ, so the last trading day of a month can differ between CSPX, ICOLCAP and the TRM; the TRM of a
  date also comes from the previous business day's trades. Both differences are small for a monthly model.
- **ICOLCAP history on Yahoo** starts on 2013-05-02 (the ETF launched in 2011). That gives 36 monthly returns from
  May-2016, before t0.

- The BanRep server does not send its intermediate certificate, so Python's default certificate bundle fails with
  `CERTIFICATE_VERIFY_FAILED`. The download uses `truststore` (the operating system's certificate store), without
  turning off verification.
- The old BanRep download link (`totoro.banrep.gov.co/analytics/saw.dll?Download...`) returned a "Sitio en
  Mantenimiento" page.
- Some weeks have no 90-day CDT deposits from the Corporaciones Financieras (BanRep notes for 2025–2026). The DTF is
  still published for those weeks.

## Sources evaluated but not used yet

- Superfinanciera, formato 523: daily return of each FIC since 2016. Each report covers one day and every fund:
  https://www.superfinanciera.gov.co/ReporteInformacionFIC/
- Superfinanciera, formato 441: CDT rates by institution and term (user manual):
  https://www.banrep.gov.co/sites/default/files/manual-usuario-tasas-de-captacion.pdf
- Investing.com, ICOLCAP history (no API; would need scraping): https://www.investing.com/etfs/icolcap-historical-data
- datos.gov.co: the "UVR - Unidad de Valor Real" dataset (`mtic-nvgq`) is only a link to the BanRep site, not data.

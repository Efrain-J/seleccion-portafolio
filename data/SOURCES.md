# Data sources

Series used by the model, where they come from and how they are used. Downloaded on 2026-11-03 with
`python -m uvr_loan.data.sources` (code in `src/uvr_loan/data/sources.py`, IDs in `config/assumptions.yaml` under
`data`). The raw files are cached in `data/raw/` and are not versioned.

## Summary

| Series | Panel column | Source | ID / ticker | Unit | Frequency | First date | Raw file |
|---|---|---|---|---|---|---|---|
| UVR | `uvr` | Banco de la República (SUAMECA) | 850 | COP per UVR | Daily | 2000-01-01 | `banrep_850.csv` |
| CDT 180 days | `cdt_180` | Banco de la República (SUAMECA), with Superfinanciera data | 67 | % effective annual, base 365 | Weekly | 1993-07-16 | `banrep_67.csv` |
| CDT 360 days | `cdt_360` | Banco de la República (SUAMECA), with Superfinanciera data | 68 | % effective annual, base 365 | Weekly | 1993-07-16 | `banrep_68.csv` |
| DTF 90 days | `fic` | Banco de la República (SUAMECA), with Superfinanciera data | 65 | % effective annual, base 365 | Weekly | 1984-01-20 | `banrep_65.csv` |
| iShares COLCAP ETF | `etf` | Yahoo Finance | `ICOLCAP.CL` | COP, close adjusted for dividends | Daily (BVC trading days) | 2015-01-02 (requested range) | `yahoo_ICOLCAP.CL.csv` |

In the monthly panel (`src/uvr_loan/data/cleaning.py`) every series takes its last value of each calendar month, and
the rates are converted from % to decimals.

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

### CDT 180 days (67)
Weighted average rate of 180-day CDTs. It is the rate of the CDT the conservative plan buys at each review, and of the
6-month CDTs of plan 2.

### CDT 360 days (68)
Weighted average rate of 360-day CDTs. It is the rate of the 12-month CDTs of plan 2.

### DTF 90 days (65)
Weighted average rate of 90-day CDTs. It is the rate of the 3-month CDTs of plan 2. **Assumption:** it is also used as
a proxy for the return of a sight FIC (money market fund), because no real fund is used yet.

## Yahoo Finance

- Ticker `ICOLCAP.CL`: iShares MSCI COLCAP (Fondo Bursátil), listed on the Bolsa de Valores de Colombia, prices in COP.
  On Yahoo its history starts in 2013.
- Downloaded with `yfinance` (`Ticker.history(auto_adjust=True)`). The adjusted close includes dividends, so the price
  change is the total return.
- Do not confuse it with `ICOL` (iShares MSCI Colombia ETF, NYSE Arca, in USD): it tracks a different index and Yahoo
  no longer returns data for it.

## Known issues

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

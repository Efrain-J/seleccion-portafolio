# UVR Loan Funding – Portfolio Selection

## What it is

A quantitative finance project on investment strategy and portfolio selection: building and backtesting a
portfolio whose job is to pay off a loan denominated in UVR (Colombia's inflation-indexed unit of account).

## Goal

Starting with **COP 760,000,000**, fund a **1,000,000 UVR** loan:

- 120-month term, rate UVR + 10% effective annual, fixed monthly payments in UVR
- 3-year full grace period (interest is capitalized)
- Scheduled prepayments of 50,000 UVR at month 48 and at month 60

The project:

1. Computes the monthly payment in UVR after the grace period.
2. Designs a portfolio that has enough cash for every payment (zero shortfall) while maximizing the final surplus.
3. Evaluates inflation and return scenarios.
4. Backtests the 10 years with real data (Oct 2016 → Oct 2026), comparing a **static** strategy (chosen once at
   t₀) with a **dynamic** one (re-estimated and rebalanced every 6 months).

## Setup

The virtual environment is managed with [uv](https://docs.astral.sh/uv/):

```
uv venv
uv pip install -e ".[dev]"
```

Lint and format with [ruff](https://docs.astral.sh/ruff/) before committing:

```
ruff check .
ruff format .
```

Run the tests with [pytest](https://docs.pytest.org/). Tests marked `network` download real data:

```
pytest -m "not network"      # offline
pytest                       # everything
pytest --cov=uvr_loan        # with coverage
```

## Usage

Generate the loan payment schedule in UVR (month by month: balance, interest, installment, prepayment and total
payment):

```
.venv\Scripts\python -m uvr_loan.amortization
```

It writes `data/processed/payment_schedule_uvr.csv` and checks that the balance at month 120 is zero. The fixed
installment for months 37–120 is 20,379.5327 UVR; months 48 and 60 add the 50,000 UVR prepayments. The
`total_payment_uvr` column is the cash the portfolio must deliver each month.

Download the market data and build the monthly panel (end of month, rates as decimals):

```
.venv\Scripts\python -m uvr_loan.data.sources     # cache in data/raw/
.venv\Scripts\python -m uvr_loan.data.cleaning    # data/processed/monthly_panel.csv
```

| Column | Source | Notes |
|---|---|---|
| `uvr` | BanRep SUAMECA, series 850 | COP per UVR, daily |
| `cdt_180` | BanRep SUAMECA, series 67 | CDT 180 days, weekly, effective annual |
| `fic` | BanRep SUAMECA, series 65 | DTF 90 days, used as a proxy for FIC returns |
| `etf` | Yahoo Finance, `ICOLCAP.CL` | iShares COLCAP, adjusted close in COP |

Endpoints, units, assumptions and known issues of every source are in [`data/SOURCES.md`](data/SOURCES.md).

Print the conservative allocation (Plan 1) at t0:

```
.venv\Scripts\python -m uvr_loan.portfolio
```

Plan 1 keeps in the FIC the payments due before the next review (high inflation scenario), puts
`conservative.equity_weight` of the rest in the ETF and the remainder in a CDT that matures at the next review. Every
parameter (t0, review frequency, ETF weight, inflation scenarios, data series) is read from
`config/assumptions.yaml`.

## Architecture

Target structure. So far `config.py`, `amortization.py`, `data/`, `inflation.py`, `cashflows.py`, `portfolio.py` and
`tests/` exist.

```
.
├── config/
│   └── assumptions.yaml      # Every problem parameter and modeling assumption
├── data/
│   ├── SOURCES.md            # Where every series comes from (versioned)
│   ├── raw/                  # Download cache (UVR, CPI, TES curves, CDT rates, COLCAP, FIC)
│   └── processed/            # Clean monthly series and payment_schedule_uvr.csv
├── notebooks/                # Exploration and charts; they import uvr_loan
├── pyproject.toml            # Package metadata and dependencies (numpy, pandas, pyyaml)
├── src/uvr_loan/
│   ├── config.py             # Loads assumptions.yaml
│   ├── amortization.py       # UVR amortization schedule (grace + prepayments)
│   ├── data/
│   │   ├── sources.py        # Automatic data download with caching
│   │   └── cleaning.py       # Builds the monthly data panel
│   ├── inflation.py          # Inflation forecasts and base/high/low scenarios
│   ├── cashflows.py          # Loan payments converted from UVR to COP (projected and realized)
│   ├── diagnosis.py          # Present value of payments, required IRR, funding ratio, duration
│   ├── assets.py             # Instruments: FIC, CDT, TES UVR, fixed-rate TES, equity
│   ├── portfolio.py          # Dedicated (cash-flow matching) + surplus portfolios; allocation profiles
│   ├── backtest/
│   │   ├── engine.py         # Monthly simulation loop with a no-look-ahead guard
│   │   ├── static.py         # Static strategy (decides once at t₀)
│   │   └── dynamic.py        # Dynamic strategy (re-estimates every k months)
│   ├── metrics.py            # Shortfalls, surplus, return/volatility, drawdown, turnover
│   ├── scenarios.py          # Stress tests and sensitivity analysis
│   └── plots.py              # Charts for the report
├── reports/                  # Final report and figures
└── tests/                    # pytest suite
```

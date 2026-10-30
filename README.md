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

## Architecture

Target structure. Most of it does not exist yet.

```
.
├── config/
│   └── assumptions.yaml      # Every problem parameter and modeling assumption
├── data/
│   ├── raw/                  # Download cache (UVR, CPI, TES curves, CDT rates, COLCAP, FIC)
│   └── processed/            # Clean monthly series
├── notebooks/                # Exploration and charts; they import uvr_loan
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

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

The environment is managed with [uv](https://docs.astral.sh/uv/). `uv.lock` pins the versions and
`.python-version` pins the interpreter; `uv run` keeps the environment in sync, so there is no need to activate it:

```
uv sync          # creates .venv, installs the project (editable) and the dev group
```

Lint and format with [ruff](https://docs.astral.sh/ruff/) before committing:

```
uv run ruff check .
uv run ruff format .
```

Run the tests with [pytest](https://docs.pytest.org/). Tests marked `network` download real data:

```
uv run pytest -m "not network"      # offline
uv run pytest                       # everything
uv run pytest --cov=uvr_loan        # with coverage
```

## Usage

Every step has a command registered in `pyproject.toml`, so `uv run <command>` is a shortcut for `uv run python -m <module>`:

| Command | Module |
|---|---|
| `uvr-amortization` | `uvr_loan.amortization` |
| `uvr-download` | `uvr_loan.data.sources` |
| `uvr-panel` | `uvr_loan.data.cleaning` |
| `uvr-portfolio` | `uvr_loan.portfolio` |
| `uvr-backtest` | `uvr_loan.backtest` |
| `uvr-synthetic` | `uvr_loan.synthetic` |

Generate the loan payment schedule in UVR (month by month: balance, interest, installment, prepayment and total
payment):

```
uv run python -m uvr_loan.amortization
```

It writes `data/processed/payment_schedule_uvr.csv` and checks that the balance at month 120 is zero. The fixed
installment for months 37–120 is 20,379.5327 UVR; months 48 and 60 add the 50,000 UVR prepayments. The
`total_payment_uvr` column is the cash the portfolio must deliver each month.

Download the market data and build the monthly panel (end of month, rates as decimals):

```
uv run python -m uvr_loan.data.sources     # cache in data/raw/
uv run python -m uvr_loan.data.cleaning    # data/processed/monthly_panel.csv
```

Naming: money ends in `_cop` or `_uvr`; rates are decimals ending in `_ea` (effective annual, known at the close of
the month and used for decisions) or `_m` (realized during the month and used for the money).

| Column | Source | Notes |
|---|---|---|
| `uvr_cop` | BanRep SUAMECA, series 850 | COP per UVR, daily |
| `cdt_90d_ea` | BanRep SUAMECA, series 65 | DTF: 90-day CDT rate, weekly, effective annual |
| `cdt_180d_ea` | BanRep SUAMECA, series 67 | CDT 180 days, weekly, effective annual |
| `cdt_360d_ea` | BanRep SUAMECA, series 68 | CDT 360 days, weekly, effective annual |
| `trm_cop` | BanRep SUAMECA, series 1 | TRM, COP per USD, daily |
| `icolcap_price_cop`, `icolcap_vol_ea` | Yahoo Finance, `ICOLCAP.CL` | iShares COLCAP, adjusted close in COP, and its annualized volatility over the last 36 months |
| `cspx_price_cop`, `cspx_vol_ea` | Yahoo Finance, `CSPX.L` × TRM | iShares Core S&P 500 UCITS (Irish, accumulating), adjusted close in USD converted to COP, and its volatility |
| `fic_index`, `fic_ret_m`, `fic_rate_ea` | Superfinanciera on datos.gov.co (`qhpu-8ixx`) | Index of the money market FICs (daily unit values, size-weighted): month-end level, return realized in the month, and that return annualized |

Endpoints, units, assumptions and known issues of every source are in [`data/SOURCES.md`](data/SOURCES.md).

Print the conservative allocation (Plan 1) at t0:

```
uv run python -m uvr_loan.portfolio
```

Plan 1 (fixed income only) keeps in the FIC the payments due before its new CDT matures (high inflation scenario; the
CDT pays the payment of the month it matures), puts `conservative.cdt_weight` of the rest in a CDT that matures at the
next review, and leaves the remainder in the FIC; during the grace period everything goes to the CDT
(`grace_cdt_weight`). Every
parameter (t0, review frequency, CDT weight, inflation scenarios, data series) is read from
`config/assumptions.yaml`. Plan 2 (CDT ladder) buys fixed-rate CDTs of 3, 6 and 12 months chosen with a linear
program in UVR that covers every remaining payment and maximizes the final wealth; the decision uses expected real
returns (deflated with the high inflation scenario, like plans 1 and 3), and the results use the observed CDT rates. Plan 3 (LDI) computes a floor, the smallest budget of that same
LP that covers every remaining payment under high inflation, gives the CDT ladder 1.05 × floor and puts the rest in
ICOLCAP and CSPX, split by inverse volatility (CPPI with multiplier 1: a fall of the ETFs never reaches the money for
the payments). Plan 4 (`ratchet_ldi`) is plan 3 with a ratchet (TIPP): it protects `protected_share` (80 %) of
the highest real surplus reached at a review (assets − cost of covering every remaining payment, in UVR), puts
(assets − protected level) / `max_fall` in the ETFs (never more than plan 3), and buys more CDTs with the rest.
Every reported peso comes from observed data. The base inflation of the
scenarios is the UVR inflation of the last `base_lookback_months` months known at each review. The full rules, with
notation, examples and simplifications, are in [`docs/reglas_de_inversion.md`](docs/reglas_de_inversion.md).

Run the dynamic backtest of every plan from t0 to the end of the horizon (reviews every `review_every_months` months):

```
uv run python -m uvr_loan.backtest
```

It writes `results/backtest/<plan>.csv` for each plan (one row per month: `uvr_cop`, `payment_cop`, `shortfall_cop`,
`etf_sold_cop`, `fic_cop`, `cdt_cop`, `etf_cop` (all ETFs) and `<name>_cop` (each ETF), `wealth_cop`, `is_review`,
`floor_cop` and `funding_ratio_total` (plan 3, at reviews: (free money + live CDTs) / (floor + live CDTs)),
`wealth_net_cop`) and `results/backtest/summary.csv` with one column per plan (months with shortfall, total shortfall, minimum
liquidity (FIC + ETF) in a payment month, ETF sold to pay, final wealth, final net wealth, annualized time-weighted
return and volatility, maximum drawdown). When
several ETFs must cover a payment, each one is sold in proportion to its value. The
net wealth deducts the accumulated shortfall, since an unpaid payment is still owed; compare plans with it. Liquidity is
FIC + ETF: a payment is
taken from the FIC first and then from ETF units sold at that month's price; only what both cannot cover is recorded
as shortfall. CDTs are never redeemed early.

Run the synthetic ETF scenarios (plans 2, 3 and 4 when the ETF prices follow made-up paths from t0, with UVR, CDT
rates, FIC and payments kept historical; see `synthetic_etfs` in the config). There are 8 scenarios: both down, flat
but volatile, one up and one down, a 40 % crash with recovery, a sine, and three where the ETFs rise on average.
Each one has `n_paths` (2,000) random paths from one `seed`, so the same seed gives the same results; plans 3 and 4
run on every path in parallel (about a minute). It writes `results/synthetic/summary.csv` (per scenario and plan:
mean and percentiles of the final net wealth, drawdown, share of paths with a shortfall, share of paths that beat
plan 3), `results/synthetic/fan.csv` (monthly percentiles of the net wealth), and for the example path 0
`results/synthetic/prices.csv` and `results/synthetic/<scenario>/<plan>.csv`;
`notebooks/synthetic_etf_scenarios.ipynb` plots them:

```
uv run python -m uvr_loan.synthetic
```

The notebook `notebooks/backtest_plans.ipynb` plots the wealth and the FIC liquidity of every plan and the real versus
projected UVR.

## Architecture

Current structure. Planned additions (diagnosis, report figures) are listed in the project plan.

```
.
├── config/
│   └── assumptions.yaml      # Every problem parameter and modeling assumption
├── docs/
│   └── reglas_de_inversion.md  # Investment rules of each plan
├── data/
│   ├── SOURCES.md            # Where every series comes from (versioned)
│   ├── raw/                  # Download cache (UVR, CDT rates, TRM, ETFs, FIC reports)
│   └── processed/            # monthly_panel.csv and payment_schedule_uvr.csv
├── notebooks/
│   ├── backtest_plans.ipynb  # Wealth, liquidity and UVR charts of every plan
│   └── synthetic_etf_scenarios.ipynb  # Plans 3 and 4 under the synthetic ETF scenarios
├── pyproject.toml            # Package metadata and dependencies (numpy, pandas, scipy, ...)
├── src/uvr_loan/
│   ├── config.py             # Loads assumptions.yaml
│   ├── amortization.py       # UVR amortization schedule (grace + prepayments)
│   ├── data/
│   │   ├── sources.py        # Automatic data download with caching
│   │   └── cleaning.py       # Builds the monthly data panel
│   ├── inflation.py          # Base inflation (last 6 months of the UVR), scenarios and projected UVR
│   ├── cashflows.py          # Review months and loan payments converted from UVR to COP
│   ├── portfolio.py          # Plan 1 rule, plan 2 LP (ladder_purchases), plan 3 floor and ETF weights
│   ├── backtest.py           # Monthly simulation of every plan (PLANS) and summary metrics
│   └── synthetic.py          # Synthetic ETF scenarios (Brownian motion + drift, crash, sine)
├── results/                  # Outputs (CSV), one folder per script
│   ├── backtest/             # <plan>.csv and summary.csv (uvr_loan.backtest)
│   └── synthetic/            # summary.csv, prices.csv and <scenario>/<plan>.csv (uvr_loan.synthetic)
└── tests/                    # pytest suite
```

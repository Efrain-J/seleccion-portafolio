"""Loads the problem parameters from config/assumptions.yaml."""

from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[2]
ASSUMPTIONS_PATH = ROOT / "config" / "assumptions.yaml"
RESULTS_DIR = ROOT / "results"
BACKTEST_DIR = RESULTS_DIR / "backtest"  # <plan>.csv and summary.csv
SYNTHETIC_DIR = RESULTS_DIR / "synthetic"  # summary.csv, prices.csv and <scenario>/<plan>.csv


def load_assumptions(path: Path = ASSUMPTIONS_PATH) -> dict[str, Any]:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)

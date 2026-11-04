from typing import Any

import pandas as pd
import pytest

from uvr_loan.amortization import schedule
from uvr_loan.config import load_assumptions


@pytest.fixture(scope="session")
def cfg() -> dict[str, Any]:
    return load_assumptions()


@pytest.fixture(scope="session")
def loan_cfg(cfg: dict[str, Any]) -> dict[str, Any]:
    return cfg["loan"]


@pytest.fixture(scope="session")
def payment_schedule(loan_cfg: dict[str, Any]) -> pd.DataFrame:
    return schedule(loan_cfg)

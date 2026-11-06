import numpy as np
import pandas as pd
import pytest
from model_helpers import BETA_COLUMNS, make_model_cfg, synthetic_betas

from uvr_loan.inflation_model.nelson_siegel import (
    implied_inflation,
    load_betas,
    nelson_siegel_nodes,
    rolling_std,
)


def test_long_tenor_tends_to_beta0():
    nodes = nelson_siegel_nodes(synthetic_betas(), np.array([1000.0]), "uvr")
    assert nodes[1000.0].iloc[0] == pytest.approx(0.05, abs=1e-3)


def test_known_value():
    betas = synthetic_betas()
    t, tau = 2.0, 2.0
    f1 = (1 - np.exp(-t / tau)) / (t / tau)
    expected = (5.0 - 1.0 * f1 + 0.5 * (f1 - np.exp(-t / tau))) / 100
    nodes = nelson_siegel_nodes(betas, np.array([2.0]), "uvr")
    assert nodes[2.0].iloc[0] == pytest.approx(expected)


def test_nodes_are_indexed_by_date_and_columns_are_tenors():
    betas = synthetic_betas()
    nodes = nelson_siegel_nodes(betas, np.arange(1, 6), "cop")
    assert nodes.shape == (len(betas), 5)
    assert list(nodes.columns) == [1, 2, 3, 4, 5]
    assert nodes.index[0] == betas["date"].iloc[0]


def test_implied_inflation_is_the_fisher_relation():
    betas = synthetic_betas().iloc[:3]
    tenors = np.arange(1, 6)
    cop = nelson_siegel_nodes(betas, tenors, "cop")
    uvr = nelson_siegel_nodes(betas, tenors, "uvr")
    np.testing.assert_allclose(
        implied_inflation(betas, tenors).to_numpy(), ((1 + cop) / (1 + uvr) - 1).to_numpy()
    )


def test_rolling_std_of_a_constant_is_zero():
    assert (rolling_std(pd.DataFrame({"a": np.ones(20)}), window=5)["a"] == 0).all()


def test_rolling_std_drops_the_initial_nans():
    assert len(rolling_std(pd.DataFrame({"a": np.arange(20.0)}), window=5)) == 16


def spanish_betas_csv(path, start="2009-12-28", periods=60):
    """Betas file as downloaded from the Banco (Spanish headers, `;`), COP empty in the first rows."""
    dates = pd.date_range(start, periods=periods, freq="D")
    table = pd.DataFrame({"Fecha": dates.strftime("%Y-%m-%d")})
    for curve in ("COP", "UVR"):
        for beta, value in zip(("B0", "B1", "B2", "TAO"), (8.0, -2.0, 1.0, 2.0), strict=True):
            table[f"{beta}_{curve}"] = value
    table.loc[:2, ["B0_COP", "B1_COP", "B2_COP", "TAO_COP"]] = np.nan
    table.to_csv(path, sep=";", index=False)
    return path


def test_load_betas_renames_filters_and_drops_incomplete_rows(tmp_path):
    cfg = make_model_cfg(betas_file=str(spanish_betas_csv(tmp_path / "b.csv")))
    betas = load_betas(cfg)
    assert list(betas.columns) == ["date", *BETA_COLUMNS]
    assert betas["date"].min() >= pd.Timestamp("2010-01-01")
    assert not betas.isna().any().any()
    assert betas["date"].is_monotonic_increasing


def test_load_betas_missing_file_says_where_to_get_it(tmp_path):
    cfg = make_model_cfg(betas_file=str(tmp_path / "missing.csv"))
    with pytest.raises(FileNotFoundError, match="SOURCES.md"):
        load_betas(cfg)


def test_load_betas_missing_columns_raises(tmp_path):
    path = tmp_path / "bad.csv"
    pd.DataFrame({"Fecha": ["2020-01-01"], "B0_COP": [1.0]}).to_csv(path, sep=";", index=False)
    with pytest.raises(ValueError, match="columns"):
        load_betas(make_model_cfg(betas_file=str(path)))

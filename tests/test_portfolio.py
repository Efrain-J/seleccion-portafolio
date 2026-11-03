import pytest

from uvr_loan.portfolio import conservative_allocation

PARAMS = {"equity_weight": 0.10}


def test_no_payments_during_grace():
    alloc = conservative_allocation(760e6, [0.0] * 6, PARAMS)
    assert alloc["fic"] == 0
    assert alloc["etf"] == pytest.approx(76e6)
    assert alloc["cdt"] == pytest.approx(684e6)
    assert alloc["shortfall"] == 0


def test_fic_covers_next_payments():
    alloc = conservative_allocation(500e6, [5e6] * 6, PARAMS)
    assert alloc["fic"] == pytest.approx(30e6)
    assert alloc["etf"] == pytest.approx(0.10 * 470e6)


@pytest.mark.parametrize(
    "wealth,payments",
    [(760e6, [0.0] * 6), (500e6, [5e6] * 6), (100e6, [90e6, 5e6])],
)
def test_allocation_adds_up_and_is_non_negative(wealth, payments):
    alloc = conservative_allocation(wealth, payments, PARAMS)
    assert alloc["fic"] + alloc["cdt"] + alloc["etf"] == pytest.approx(wealth)
    assert min(alloc["fic"], alloc["cdt"], alloc["etf"]) >= 0


def test_shortfall_when_payments_exceed_wealth():
    alloc = conservative_allocation(10e6, [8e6, 8e6], PARAMS)
    assert alloc["fic"] == pytest.approx(10e6)
    assert alloc["cdt"] == 0
    assert alloc["etf"] == 0
    assert alloc["shortfall"] == pytest.approx(6e6)

"""Two-stage availability rules: physical status first, then partial allocation over the window."""
import pytest

from app.availability import effective_available_stock, evaluate_request

MIC = {"id": "e1", "status": "Available", "totalQuantity": 10}


def test_unavailable_equipment_has_no_stock_even_when_nothing_is_reserved():
    assert effective_available_stock({**MIC, "status": "Unavailable"}, 0) == 0


def test_unknown_equipment_or_status_has_no_stock():
    assert effective_available_stock(None, 0) == 0
    assert effective_available_stock({**MIC, "status": "Unknown"}, 0) == 0


@pytest.mark.parametrize("reserved,expected", [(0, 10), (4, 6), (10, 0)])
def test_partial_booking_leaves_the_remaining_pool_available(reserved, expected):
    assert effective_available_stock(MIC, reserved) == expected


def test_over_booked_pool_is_clamped_to_zero():
    assert effective_available_stock(MIC, 13) == 0


@pytest.mark.parametrize("requested,insufficient", [(6, False), (7, True)])
def test_request_is_insufficient_only_when_it_exceeds_the_remaining_balance(requested, insufficient):
    result = evaluate_request({"quantityRequested": requested}, MIC, 4)
    assert result == {"reservedQuantity": 4, "availableStock": 6, "isInsufficient": insufficient}

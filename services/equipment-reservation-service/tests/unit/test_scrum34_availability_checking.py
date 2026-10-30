"""
SCRUM-34: Equipment Availability Checking

User Story
----------
As a Technical Support Staff, I want the system to automatically filter out
equipment that's marked unavailable so that I can review equipment that can be
used for the Event Request.

Acceptance Criteria
-------------------
AC1: The equipment list shown to Technical Support Staff for a given request
     must display: item name, requested quantity, and current status
     (Available, Unavailable).
AC2: Given a unit of equipment is marked Unavailable in the system, when the
     equipment list is generated, then that unit is excluded from the units
     counted as available for this request.

Real
----
- The Equipment Reservation routes and app.clients run for real against a fake
  world; the two-stage availability rules in app.availability run for real.
- Assertions are on the status, the response body and which downstream calls
  the composite makes.

Doubled
-------
- Event, Equipment and Equipment Request Services: Fake (tests/unit/fakes.py
  `World`, wired in by the `world` fixture) - in-memory events, assignments,
  catalogue and request lines; world.calls records which calls were made.
- httpx.request (client tests): Stub (`sent` fixture) - canned FakeResponse;
  the recorded method, URL and headers are inspected.

Not proven
----------
- That the review page shows item name, quantity and status for each line (AC1,
  UI half) (-> frontend EquipmentRequestsPage.test.tsx and e2e
  equipment.spec.ts).
- That Equipment Service's stored operational status is current (NOT COVERED
  ANYWHERE).
"""

import pytest

from app import clients, create_app
from app.availability import RESERVING_EVENT_STATUSES, effective_available_stock, evaluate_request
from app.clients import DownstreamError
from tests.unit.factories import COORDINATOR, CREATE_URL, LEAD, TS, bearer, new_item, rows
from tests.unit.fakes import END, LAPTOP, MIC, OTHER, START, TABLE, TARGET, THIRD, USER, FakeResponse, equipment, line

HEADERS = {"Authorization": "Bearer user-token", "Cookie": "must-not-be-forwarded"}
MIC_STOCK = {"id": "e1", "status": "Available", "totalQuantity": 10}


def test_review_list_when_equipment_unavailable_shows_zero_available(world, client):
    """
    Summary: Equipment marked Unavailable counts as zero units available, whatever else is booked.
    AC2: Given a unit of equipment is marked Unavailable in the system, when
        the equipment list is generated, then that unit is excluded from the
        units counted as available for this request.
    Double: Fake (world: catalogue marks LAPTOP Unavailable)
    """
    # Arrange (Given)
    world.requests = [line("r1", TARGET, LAPTOP, 1)]

    # Act (When)
    event = rows(client)[0]

    # Assert (Then)
    assert event["requests"][0]["availability"]["availableStock"] == 0
    assert event["requests"][0]["availability"]["isInsufficient"] is True
    assert event["requests"][0]["equipment"] == {"description": "Laptop", "type": "Microphone", "totalQuantity": 8, "status": "Unavailable"}
    assert world.catalogue[2]["status"] == "Unavailable"  # never written to


def test_review_list_when_equipment_not_in_catalogue_shows_zero_available(world, client):
    """
    Summary: Equipment that is no longer in the catalogue counts as zero units available.
    AC2: Given a unit of equipment is marked Unavailable in the system, when
        the equipment list is generated, then that unit is excluded from the
        units counted as available for this request.
    Double: Fake (world: request for an id the catalogue lacks)
    """
    # Arrange (Given)
    world.requests = [line("r1", TARGET, "00000000-0000-4000-8000-00000000ffff", 1)]

    # Act (When)
    request = rows(client)[0]["requests"][0]

    # Assert (Then)
    assert request["equipment"] is None and request["availability"]["isInsufficient"] is True


@pytest.mark.parametrize("equipment_id", [LAPTOP, "00000000-0000-4000-8000-00000000ffff"], ids=["unavailable", "not_in_catalogue"])
def test_approve_line_when_equipment_unavailable_or_unknown_returns_409(world, client, equipment_id):
    """
    Summary: A line for unavailable or unknown equipment cannot be approved.
    AC2: Given a unit of equipment is marked Unavailable in the system, when
        the equipment list is generated, then that unit is excluded from the
        units counted as available for this request.
    Double: Fake (world: catalogue marks LAPTOP Unavailable / lacks the id)
    """
    # Arrange (Given)
    request_id = "00000000-0000-4000-8000-0000000000d5"
    world.requests = [line(request_id, TARGET, equipment_id, 1)]

    # Act (When)
    response = client.patch(f"/equipment-reservations/requests/{request_id}", headers=TS, json={"status": "Approved"})

    # Assert (Then)
    assert response.status_code == 409
    assert not any(call[0] == "review_request" for call in world.calls)


def test_review_list_when_lines_decided_shows_no_availability(world, client):
    """
    Summary: Already decided lines show no availability figures and need no stock lookup.
    AC1: The equipment list shown to Technical Support Staff for a given
        request must display: item name, requested quantity, and current status
        (Available, Unavailable).
    Double: Fake (world: only decided lines; world.calls inspected)
    """
    world.requests = [line("r1", TARGET, MIC, 3, "Approved"), line("r2", TARGET, TABLE, 3, "Rejected")]

    event = rows(client)[0]

    assert [r["availability"] for r in event["requests"]] == [None, None]
    assert not any(call[0] == "overlapping" for call in world.calls)


def test_effective_stock_when_equipment_unavailable_is_zero():
    """
    Summary: An Unavailable item has no usable units even when nothing is reserved.
    AC2: Given a unit of equipment is marked Unavailable in the system, when
        the equipment list is generated, then that unit is excluded from the
        units counted as available for this request.
    Double: None
    """
    # Act + Assert (When / Then)
    assert effective_available_stock({**MIC_STOCK, "status": "Unavailable"}, 0) == 0


def test_effective_stock_when_equipment_or_status_unknown_is_zero():
    """
    Summary: An item that is missing or has an unknown status has no usable units.
    AC2: Given a unit of equipment is marked Unavailable in the system, when
        the equipment list is generated, then that unit is excluded from the
        units counted as available for this request.
    Double: None
    """
    # Act + Assert (When / Then)
    assert effective_available_stock(None, 0) == 0
    assert effective_available_stock({**MIC_STOCK, "status": "Unknown"}, 0) == 0

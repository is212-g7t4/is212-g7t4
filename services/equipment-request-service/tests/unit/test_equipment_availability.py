"""SCRUM-34: Equipment Availability Checking

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
- Real owner review route, catalogue validation and allocation evaluation refuse unusable items.

Doubled
-------
- Stub (database cursor selected rows); Fake (trusted composite caller supplies catalogue); Stub (JWKS lookup).

Not proven
----------
- AC1 display is not exercised; UI and current catalogue persistence are NOT COVERED ANYWHERE in this module.
- AC2 is checked against supplied status only; the real Equipment Service and database persistence are not proved here.
- Missing-catalogue fail-closed behaviour is a supporting reliability check, not an additional Jira AC.
"""

import pytest

from tests.unit.factories import EVENT_ID, MIC, REQUEST_ID, USER_ID, bearer, db_row, approval_context



@pytest.mark.parametrize("case", ["unavailable", "missing_equipment"], ids=["unavailable", "missing_catalogue_item"])
def test_approval_when_equipment_unavailable_or_missing_refuses_stock(setup, case):
    """Summary: Released/non-overlapping holders permit reuse; unavailable/unknown catalogue refuses it.
    AC2: Unavailable equipment is excluded from the usable stock.
    Double: Stub (owner rows and catalogue context); Fake (trusted composite caller)
    """
    # Arrange (Given): test data and external adapters from fixtures.
    client, cursor, _ = setup
    checked = approval_context(total=20)
    held = []
    if case in ("nonoverlap", "cancelled"):
        event = {**checked["events"][0], "id": USER_ID}
        if case == "cancelled": event["status"] = "Cancelled"
        else: event.update(startTime="2030-01-01T18:00:00+08:00", endTime="2030-01-02T00:00:00+08:00")
        checked["events"].append(event)
        held = [db_row(event_id=USER_ID, status="Approved", quantity_requested=20)]
    elif case == "unavailable": checked["equipment"][0]["status"] = "Unavailable"
    elif case == "missing_equipment": checked["equipment"] = []
    cursor.fetchall.side_effect = [[db_row()], held, [db_row(status="Approved")]]
    # Act + Assert (When / Then): exercise the request/calculation and inspect outcomes.
    response = client.patch(f"/equipment-requests/{REQUEST_ID}", headers=bearer(USER_ID, "Technical Support"), json={"status": "Approved", "approvalContext": checked})
    assert response.status_code == (409 if case in ("unavailable", "missing_equipment") else 200)

"""
SCRUM-34: Equipment Availability Checking

User Story
----------
As a Technical Support Staff, I want the system to automatically filter out equipment that's marked unavailable so that I can review equipment that can be used for the Event Request.

Acceptance Criteria
-------------------
AC1: The equipment list shown to Technical Support Staff for a given request must display: item name, requested quantity, and current status (Available, Unavailable).
AC2: Given a unit of equipment is marked Unavailable in the system, when the equipment list is generated, then that unit is excluded from the units counted as available for this request.

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
    """Summary: An Unavailable or missing catalogue item cannot be approved, even with nominal stock.
    AC2: Given a unit of equipment is marked Unavailable in the system, when the equipment list is generated, then that unit is excluded from the units counted as available for this request.
    Double: Stub (canned database results/errors); Mock (database interactions inspected); Stub (test JWKS public key for user-token verification); Fake (CompositeClient adds synthetic service context to JSON writes; no HTTP service runs)
    """
    # Arrange (Given): test data and external adapters from fixtures.
    client, cursor, _ = setup
    checked = approval_context(total=20)
    if case == "unavailable":
        checked["equipment"][0]["status"] = "Unavailable"
    else:
        checked["equipment"] = []
    cursor.fetchall.side_effect = [[db_row()], [], [db_row(status="Approved")]]
    # Act + Assert (When / Then): exercise the request/calculation and inspect outcomes.
    response = client.patch(f"/equipment-requests/{REQUEST_ID}", headers=bearer(USER_ID, "Technical Support"), json={"status": "Approved", "approvalContext": checked})
    assert response.status_code == 409
    assert not any(call.args[0].lstrip().startswith("UPDATE") for call in cursor.execute.call_args_list)

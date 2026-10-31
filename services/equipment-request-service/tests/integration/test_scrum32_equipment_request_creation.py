"""
SCRUM-32: Create Event Equipment Request

User Story
----------
As an Event Coordinator and Event Coordinator Lead, I want to record the equipment required for an event so that the technical team is informed of the resources needed as requested.

Acceptance Criteria
-------------------
AC1: The system allows the Event Coordinator and Event Coordinator Lead to record the equipment, equipment type, quantity, and relevant technical requirements for an event.
AC2: Recorded equipment request accurately reflects the date and time of the corresponding event
AC3: Ensure newly recorded equipment requests default to an initial status such as "Pending"

Real
----
- Flask creation route, signed user role checks, request SQL and real PostgreSQL foreign-key enforcement in a disposable owner database.

Doubled
-------
- JWKS key lookup and supplied notification context; Event/User/Equipment rows are inert FK scaffolding, not live services.

Not proven
----------
- UI form, catalogue/type lookup, event schedule/assignment validation and inbox delivery. AC2 event date/time lives outside this request schema. The owner fixture uses selected baseline tables plus the outbox migration, not the full migration chain.

- Supporting atomicity guard, not proof of catalogue/type or event schedule validation. Applies to: `test_creation_when_second_equipment_foreign_key_is_missing_rolls_back_first_line_and_all_jobs`.
"""
import pytest

from tests.integration.equipment_request_db_helpers import uid

pytestmark = pytest.mark.integration


def test_creation_when_second_equipment_foreign_key_is_missing_rolls_back_first_line_and_all_jobs(owner):
    """Summary: A genuine foreign-key failure on the second line saves neither the valid first line nor any notification intent.
    AC1: The system allows the Event Coordinator and Event Coordinator Lead to record the equipment, equipment type, quantity, and relevant technical requirements for an event.
    Double: Stub (Supabase JWKS lookup supplies a test signing key); Stub (JWT clock fixed for local token verification); Stub (supplied external event/catalogue or notification context; no upstream service runs); PostgreSQL connections, SQL and transactions are real, not doubles
    """
    missing = uid()
    owner.db.execute("""CREATE SEQUENCE successful_request_inserts;
        CREATE FUNCTION count_successful_request_insert() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            PERFORM nextval('successful_request_inserts');
            RETURN NEW;
        END $$;
        CREATE TRIGGER count_request_insert AFTER INSERT ON public."EquipmentRequest"
        FOR EACH ROW EXECUTE FUNCTION count_successful_request_insert();""")
    before = owner.db.snapshot()
    context = {**owner.context, "equipmentNames": {**owner.context["equipmentNames"], missing: "Missing equipment"}}
    response = owner.client.post(
        f"/events/{owner.event}/equipment-requests",
        headers=owner.identity("Event Coordinator", owner.coordinator),
        json={"items": [
            {"equipmentId": owner.equipment[0], "quantityRequested": 5},
            {"equipmentId": missing, "quantityRequested": 2},
        ], "notificationContext": context},
    )
    assert response.status_code == 404, response.json
    assert response.json == {"message": "The event, requester or an equipment item no longer exists."}
    assert owner.db.execute("SELECT last_value,is_called FROM successful_request_inserts") == [{"last_value": 1, "is_called": True}]
    assert owner.db.snapshot() == before

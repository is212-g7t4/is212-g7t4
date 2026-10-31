"""SCRUM-31: Equipment Catalogue

User Story
----------
As a Technical Support Staff member, I want to add equipment records in the catalogue so that the system reflects our current physical inventory.

Acceptance Criteria
-------------------
AC1: Can input and add new equipment records
AC2: Must display the list of available equipments

Real
----
- Catalogue Flask routes, signed role checks, validation, models and full-migration disposable PostgreSQL. Assertions compare HTTP values with independently committed rows.

Doubled
-------
- Stub (JWKS key lookup trusts the local test signing key); Supabase sign-in itself is not run.

Not proven
----------
- Browser display and upstream equipment reservations are outside this owner.
- Field restrictions and rejected writes are supporting validation/access contracts, not new SCRUM-31 ACs. The fixture owns database/container cleanup; this module does not start any application service.
"""

import pytest

from tests.unit.factories import bearer

pytestmark = [pytest.mark.integration, pytest.mark.enable_socket]
STAFF = bearer("10000000-0000-4000-8000-000000000001", "Technical Support")
SETUP = "Mount or place on a stable surface, connect HDMI and a power outlet, then align the image."


def equipment_payload(**overrides):
    return dict(equipmentType="projector", description=" 4K projector ", totalQuantity=5,
                location=" Tech Store ", **overrides)


def catalogue_rows(db):
    return db.execute('SELECT equipment_id::text AS id, equipment_type AS type, description, '
                      'total_quantity AS "totalQuantity", location, operational_status AS status '
                      'FROM public."Equipment" ORDER BY equipment_id')


def test_ac1_created_equipment_is_committed_and_read_back(client, db):
    """Summary: Technical Support adds a catalogue item and a fresh read returns its committed values.
AC1: Can input and add new equipment records
AC2: Must display the list of available equipments
Double: Stub (local signing-key lookup only).
"""
    response = client.post("/equipment", headers=STAFF, json=equipment_payload())
    assert response.status_code == 201
    expected = dict(id=response.json["equipment"]["id"], type="Projector", description="4K projector",
                    totalQuantity=5, location="Tech Store", status="Available")
    assert catalogue_rows(db) == [expected]
    assert response.json == {"equipment": {**expected, "setupRequirements": SETUP}}
    listed = client.get("/equipment", headers=STAFF)
    assert listed.status_code == 200
    assert listed.json == {"equipment": [{**expected, "setupRequirements": SETUP}]}


def test_ac2_available_filter_excludes_committed_unavailable_item(client, db):
    """Summary: The availability filter returns only the available item from a real mixed catalogue.
AC2: Must display the list of available equipments
Double: Stub (local signing-key lookup only).
"""
    identifiers = ["20000000-0000-4000-8000-000000000001", "20000000-0000-4000-8000-000000000002"]
    for identifier, status in zip(identifiers, ["Available", "Unavailable"]):
        db.execute('INSERT INTO public."Equipment" (equipment_id,equipment_type,description,total_quantity,location,operational_status) '
                   'VALUES (%s,%s,%s,%s,%s,%s)', [identifier, "Projector", status + " projector", 5, "Tech Store", status])
    before = catalogue_rows(db)
    assert len(before) == 2
    response = client.get("/equipment?status=Available", headers=STAFF)
    assert response.status_code == 200
    assert response.json == {"equipment": [dict(id=identifiers[0], type="Projector", description="Available projector",
        totalQuantity=5, location="Tech Store", status="Available", setupRequirements=SETUP)]}
    assert catalogue_rows(db) == before


def test_ac1_invalid_quantity_does_not_create_equipment(client, db):
    """Summary: Invalid catalogue quantity is refused without committing any record.
AC1: Can input and add new equipment records
Double: Stub (local signing-key lookup only).
"""
    payload = equipment_payload()
    payload["totalQuantity"] = -1
    assert catalogue_rows(db) == []
    response = client.post("/equipment", headers=STAFF, json=payload)
    assert response.status_code == 400
    assert response.json == {"message": "totalQuantity must be a whole number of 0 or more."}
    assert catalogue_rows(db) == []


def test_ac1_unauthorised_role_does_not_create_equipment(client, db):
    """Summary: An Event Coordinator cannot add physical catalogue stock.
AC1: Can input and add new equipment records
Double: Stub (local signing-key lookup only).
"""
    assert catalogue_rows(db) == []
    response = client.post("/equipment", headers=bearer(
        "10000000-0000-4000-8000-000000000002", "Event Coordinator"), json=equipment_payload())
    assert response.status_code == 403
    assert response.json == {"message": "Only Technical Support can add equipment."}
    assert catalogue_rows(db) == []

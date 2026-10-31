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
- app.equipment: the Equipment class hierarchy, each subclass's
  get_setup_requirements(), the from_row() factory and to_dict() run for real;
  no dependencies.
- Assertions are on the class returned, its setup requirements and the
  serialised shape the catalogue list sends.

Doubled
-------
- Nothing: pure logic.

Not proven
----------
- AC1: Adding records is tested through the catalogue API module, not this pure model module.
- AC2: Every known type, unknown-type fallback and complete serialised defaults are checked; SQL/browser list behaviour is outside this model seam.
- Exact setup instructions, type inheritance and known-type registry are supporting design rules absent from these ACs. SCRUM-113 is a task without acceptance criteria; its useful structural regressions are preserved pending a Product Owner decision.
"""
import pytest

from app.equipment import (
    EQUIPMENT_TYPES,
    Chair,
    Equipment,
    Furniture,
    Laptop,
    LightingKit,
    Microphone,
    Projector,
    Speaker,
    Table,
    from_row,
)

ALL = (Microphone, LightingKit, Projector, Laptop, Furniture, Table, Chair, Speaker)

EXPECTED_SETUP_REQUIREMENTS = {'Microphone': 'Fresh batteries, sound check and a stand or lectern mount.', 'LightingKit': 'Mount on stands, run power cabling and focus before doors open.', 'Projector': 'Mount or place on a stable surface, connect HDMI and a power outlet, then align the image.', 'Laptop': 'Fully charged, presentation loaded, with a charger and HDMI adapter.', 'Furniture': 'Arrange to the event layout and keep walkways clear.', 'Table': 'Place per the layout, level the legs and add table covers if required.', 'Chair': 'Set out in rows per the layout, with accessible seating reserved.', 'Speaker': 'Position at the front, connect to the mixer and run a sound check.'}


def row(equipment_type):
    return {
        "equipment_id": "11111111-1111-1111-1111-111111111111",
        "equipment_type": equipment_type,
        "description": "Thing",
        "total_quantity": 3,
        "location": "Store",
        "operational_status": "Available",
    }


@pytest.mark.parametrize("cls", ALL, ids=["microphone", "lighting_kit", "projector", "laptop", "furniture", "table", "chair", "speaker"])
def test_from_row_with_known_type_returns_matching_subclass(cls):
    """Summary: A catalogue row becomes the right kind of equipment, listed with that type's setup requirements.
AC2: Must display the list of available equipments
Double: None
"""
    item = from_row(row(cls.__name__))
    assert type(item) is cls
    assert item.get_setup_requirements() == EXPECTED_SETUP_REQUIREMENTS[cls.__name__]
    assert item.to_dict()["setupRequirements"] == EXPECTED_SETUP_REQUIREMENTS[cls.__name__]


def test_setup_requirements_when_compared_differ_for_every_type():
    """Summary: No two known types share the same setup requirements.
AC2: Must display the list of available equipments
Double: None
"""
    texts = {from_row(row(name)).get_setup_requirements() for name in EQUIPMENT_TYPES}
    assert len(texts) == len(EQUIPMENT_TYPES)


def test_from_row_with_unknown_type_returns_generic_equipment():
    """Summary: An item of a type the system does not know is still listed, with generic setup requirements.
AC2: Must display the list of available equipments
Double: None
"""
    item = from_row(row("Drone"))
    assert type(item) is Equipment
    assert item.get_setup_requirements() == "Check the item is present and working before the event."


def test_to_dict_with_missing_values_returns_list_shape_with_defaults():
    """Summary: A listed item always has every field, with blanks and Unknown status in place of missing values.
AC2: Must display the list of available equipments
Double: None
"""
    data = Equipment("id-1", "Laptop", None, 2, None, None).to_dict()
    assert data == {
        "id": "id-1",
        "type": "Laptop",
        "description": "",
        "totalQuantity": 2,
        "location": "",
        "status": "Unknown",
        "setupRequirements": "Check the item is present and working before the event.",
    }


# --- Supporting/supplementary design checks ----------------------------------
# No Jira acceptance criterion covers these. They check design decisions the
# stories rely on (health check, CORS, configuration and failure handling).

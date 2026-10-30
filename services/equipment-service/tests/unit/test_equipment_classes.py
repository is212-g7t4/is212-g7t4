"""
SCRUM-31: Equipment Catalogue

User Story
----------
As a Technical Support Staff member, I want to add equipment records in the
catalogue so that the system reflects our current physical inventory.

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
- That the catalogue page shows the setup requirements (-> frontend
  EquipmentPage.test.tsx).
- That the hierarchy matches the OO diagram (SCRUM-113 has no ACs; NOT COVERED
  ANYWHERE).
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
    """
    Summary: A catalogue row becomes the right kind of equipment, listed with that type's setup requirements.
    AC2: Must display the list of available equipments
    Double: None
    """
    item = from_row(row(cls.__name__))
    assert type(item) is cls
    assert item.get_setup_requirements()
    assert item.to_dict()["setupRequirements"] == item.get_setup_requirements()


def test_setup_requirements_when_compared_differ_for_every_type():
    """
    Summary: No two known types share the same setup requirements.
    AC2: Must display the list of available equipments
    Double: None
    """
    texts = {from_row(row(name)).get_setup_requirements() for name in EQUIPMENT_TYPES}
    assert len(texts) == len(EQUIPMENT_TYPES)


def test_from_row_with_unknown_type_returns_generic_equipment():
    """
    Summary: An item of a type the system does not know is still listed, with generic setup requirements.
    AC2: Must display the list of available equipments
    Double: None
    """
    item = from_row(row("Drone"))
    assert type(item) is Equipment
    assert item.get_setup_requirements()


def test_to_dict_with_missing_values_returns_list_shape_with_defaults():
    """
    Summary: A listed item always has every field, with blanks and Unknown status in place of missing values.
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
        "setupRequirements": Equipment.get_setup_requirements(None),
    }


# --- Supporting/supplementary design checks ----------------------------------
# No Jira acceptance criterion covers these. They check design decisions the
# stories rely on (health check, CORS, configuration and failure handling).


def test_equipment_subclasses_when_defined_inherit_and_override_setup_requirements():
    """
    Summary: Every equipment type is an Equipment with its own setup requirements.
    Supporting design check: the equipment OO model (SCRUM-113 is a task with
        no ACs)
    Double: None
    """
    for cls in ALL:
        assert issubclass(cls, Equipment)
        assert "get_setup_requirements" in cls.__dict__


def test_table_and_chair_when_defined_inherit_through_furniture():
    """
    Summary: Tables and chairs are modelled as kinds of furniture.
    Supporting design check: the equipment OO model (SCRUM-113 is a task with
        no ACs)
    Double: None
    """
    assert issubclass(Table, Furniture) and issubclass(Chair, Furniture)
    assert Table.__bases__ == (Furniture,) and Chair.__bases__ == (Furniture,)

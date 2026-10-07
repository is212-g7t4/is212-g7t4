"""OO model: inheritance, polymorphism and the row factory."""
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


def test_every_subclass_is_an_equipment_and_overrides_setup_requirements():
    for cls in ALL:
        assert issubclass(cls, Equipment)
        assert "get_setup_requirements" in cls.__dict__


def test_table_and_chair_inherit_through_furniture():
    assert issubclass(Table, Furniture) and issubclass(Chair, Furniture)
    assert Table.__bases__ == (Furniture,) and Chair.__bases__ == (Furniture,)


@pytest.mark.parametrize("cls", ALL)
def test_factory_returns_matching_subclass_with_own_requirements(cls):
    item = from_row(row(cls.__name__))
    assert type(item) is cls
    assert item.get_setup_requirements()
    assert item.to_dict()["setupRequirements"] == item.get_setup_requirements()


def test_setup_requirements_differ_by_type():
    texts = {from_row(row(name)).get_setup_requirements() for name in EQUIPMENT_TYPES}
    assert len(texts) == len(EQUIPMENT_TYPES)


def test_unknown_type_falls_back_to_base_class():
    item = from_row(row("Drone"))
    assert type(item) is Equipment
    assert item.get_setup_requirements()


def test_to_dict_shape_and_defaults():
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

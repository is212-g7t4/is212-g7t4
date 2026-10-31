"""Infra: equipment model structure, supporting SCRUM-113 (a task without ACs).

Real
----
Equipment class inheritance and method declarations are inspected without I/O.

Doubled
-------
None: these are structural model checks.

Not proven
----------
No Jira acceptance criterion requires these exact inheritance choices. Preserve
these useful regressions pending a Product Owner decision; no AC is invented.
This module does not prove catalogue creation, SQL persistence or UI rendering.
"""
from app.equipment import Equipment, Furniture, Microphone, LightingKit, Projector, Laptop, Table, Chair, Speaker
ALL = (Microphone, LightingKit, Projector, Laptop, Furniture, Table, Chair, Speaker)


def test_equipment_subclasses_when_defined_inherit_and_override_setup_requirements():
    """Summary: Every equipment type is an Equipment with its own setup requirements.
Double: None
Supporting design check: the equipment OO model (SCRUM-113 is a task with no ACs)
"""
    for cls in ALL:
        assert issubclass(cls, Equipment)
        assert "get_setup_requirements" in cls.__dict__



def test_table_and_chair_when_defined_inherit_through_furniture():
    """Summary: Tables and chairs are modelled as kinds of furniture.
Double: None
Supporting design check: the equipment OO model (SCRUM-113 is a task with no ACs)
"""
    assert issubclass(Table, Furniture) and issubclass(Chair, Furniture)
    assert Table.__bases__ == (Furniture,) and Chair.__bases__ == (Furniture,)

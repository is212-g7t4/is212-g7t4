"""OO model for the equipment catalogue (see the Equipment class diagram).

`Equipment` mirrors the `public."Equipment"` table. Each equipment_type has a
subclass that overrides `get_setup_requirements()`, so a caller holding any
`Equipment` gets the version for the object's actual type (polymorphism).
"""

STATUSES = ("Available", "Unavailable")


class Equipment:
    def __init__(
        self,
        equipment_id,
        equipment_type,
        description,
        total_quantity,
        location,
        operational_status,
    ):
        self.equipment_id = equipment_id
        self.equipment_type = equipment_type
        self.description = description
        self.total_quantity = total_quantity
        self.location = location
        self.operational_status = operational_status

    def get_setup_requirements(self):
        return "Check the item is present and working before the event."

    def to_dict(self):
        return {
            "id": str(self.equipment_id),
            "type": self.equipment_type,
            "description": self.description or "",
            "totalQuantity": self.total_quantity,
            "location": self.location or "",
            "status": self.operational_status or "Unknown",
            "setupRequirements": self.get_setup_requirements(),
        }


class Microphone(Equipment):
    def get_setup_requirements(self):
        return "Fresh batteries, sound check and a stand or lectern mount."


class LightingKit(Equipment):
    def get_setup_requirements(self):
        return "Mount on stands, run power cabling and focus before doors open."


class Projector(Equipment):
    def get_setup_requirements(self):
        return "Mount or place on a stable surface, connect HDMI and a power outlet, then align the image."


class Laptop(Equipment):
    def get_setup_requirements(self):
        return "Fully charged, presentation loaded, with a charger and HDMI adapter."


class Furniture(Equipment):
    def get_setup_requirements(self):
        return "Arrange to the event layout and keep walkways clear."


class Table(Furniture):
    def get_setup_requirements(self):
        return "Place per the layout, level the legs and add table covers if required."


class Chair(Furniture):
    def get_setup_requirements(self):
        return "Set out in rows per the layout, with accessible seating reserved."


class Speaker(Equipment):
    def get_setup_requirements(self):
        return "Position at the front, connect to the mixer and run a sound check."


EQUIPMENT_CLASSES = {
    cls.__name__: cls
    for cls in (Microphone, LightingKit, Projector, Laptop, Furniture, Table, Chair, Speaker)
}
EQUIPMENT_TYPES = tuple(EQUIPMENT_CLASSES)


def from_row(row):
    """Build the subclass matching the row's equipment_type (base class if unknown)."""
    cls = EQUIPMENT_CLASSES.get(row["equipment_type"], Equipment)
    return cls(
        row["equipment_id"],
        row["equipment_type"],
        row["description"],
        row["total_quantity"],
        row["location"],
        row["operational_status"],
    )

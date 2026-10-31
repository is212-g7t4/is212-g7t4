"""
SUPPORTING DESIGN CHECKS: Equipment seed catalogue

User Story
----------
Supporting/supplementary design checks. No story or acceptance
criterion describes the behaviour these tests check; it is plumbing
that every story of this service relies on.

Real
----
- scripts/seed_equipment.py's EQUIPMENT and STATUSES are loaded for real and
  passed through app.equipment.from_row().
- Assertions are on the seed rows' types, statuses, quantities and keys.

Doubled
-------
- Nothing: the seed module is imported directly; no database is touched.

Not proven
----------
- That running the seed script against Supabase inserts these rows (NOT COVERED
  ANYWHERE).
"""
import importlib.util
from pathlib import Path

import pytest

from app.equipment import EQUIPMENT_TYPES, STATUSES, from_row

SEED_PATH = Path(__file__).resolve().parents[2] / "scripts" / "seed_equipment.py"
spec = importlib.util.spec_from_file_location("seed_equipment", SEED_PATH)
seed_equipment = importlib.util.module_from_spec(spec)
spec.loader.exec_module(seed_equipment)


# --- Supporting/supplementary design checks ----------------------------------
# No Jira acceptance criterion covers these. They check design decisions the
# stories rely on (health check, CORS, configuration and failure handling).


@pytest.mark.parametrize("item", seed_equipment.EQUIPMENT, ids=lambda i: i["description"])
def test_seed_row_when_loaded_uses_known_type_and_status(item):
    """Summary: Every seed item uses a known type and status, a whole quantity, and has a description and location.
Double: None
Supporting design check: the seed catalogue is valid catalogue data
"""
    assert item["equipment_type"] in EQUIPMENT_TYPES
    assert item["operational_status"] in seed_equipment.STATUSES
    assert isinstance(item["total_quantity"], int) and item["total_quantity"] >= 0
    assert item["description"] and item["location"]


def test_seed_statuses_when_compared_match_service_statuses():
    """Summary: The seed script and the service agree on the list of operational statuses.
Double: None
Supporting design check: the seed catalogue is valid catalogue data
"""
    assert seed_equipment.STATUSES == STATUSES


def test_seed_catalogue_when_loaded_covers_every_type_and_status():
    """Summary: The seed catalogue includes at least one item of every type and every status.
Double: None
Supporting design check: the seed catalogue exercises every type and status
"""
    assert {i["equipment_type"] for i in seed_equipment.EQUIPMENT} == set(EQUIPMENT_TYPES)
    assert {i["operational_status"] for i in seed_equipment.EQUIPMENT} == set(STATUSES)


def test_seed_catalogue_when_loaded_has_no_duplicate_items():
    """Summary: No item appears twice in the seed catalogue.
Double: None
Supporting design check: the seed catalogue is valid catalogue data
"""
    keys = [(i["equipment_type"], i["description"]) for i in seed_equipment.EQUIPMENT]
    assert len(keys) == len(set(keys))


def test_seed_row_when_built_through_factory_lists_with_requirements():
    """Summary: A seed item turns into a listable equipment record with setup requirements.
Double: None
Supporting design check: the seed catalogue is valid catalogue data
"""
    item = seed_equipment.EQUIPMENT[0]
    data = from_row({"equipment_id": "x", **item}).to_dict()
    assert data["type"] == item["equipment_type"] and data["setupRequirements"]

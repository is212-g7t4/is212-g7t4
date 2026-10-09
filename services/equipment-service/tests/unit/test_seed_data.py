"""The seed catalogue must use known types and statuses and survive the OO factory."""
import importlib.util
from pathlib import Path

import pytest

from app.equipment import EQUIPMENT_TYPES, STATUSES, from_row

SEED_PATH = Path(__file__).resolve().parents[2] / "scripts" / "seed_equipment.py"
spec = importlib.util.spec_from_file_location("seed_equipment", SEED_PATH)
seed_equipment = importlib.util.module_from_spec(spec)
spec.loader.exec_module(seed_equipment)


@pytest.mark.parametrize("item", seed_equipment.EQUIPMENT, ids=lambda i: i["description"])
def test_seed_rows_match_catalogue_shape(item):
    assert item["equipment_type"] in EQUIPMENT_TYPES
    assert item["operational_status"] in seed_equipment.STATUSES
    assert isinstance(item["total_quantity"], int) and item["total_quantity"] >= 0
    assert item["description"] and item["location"]


def test_seed_statuses_match_the_service():
    assert seed_equipment.STATUSES == STATUSES


def test_seed_covers_every_type_and_status():
    assert {i["equipment_type"] for i in seed_equipment.EQUIPMENT} == set(EQUIPMENT_TYPES)
    assert {i["operational_status"] for i in seed_equipment.EQUIPMENT} == set(STATUSES)


def test_seed_keys_are_unique():
    keys = [(i["equipment_type"], i["description"]) for i in seed_equipment.EQUIPMENT]
    assert len(keys) == len(set(keys))


def test_seed_rows_survive_the_factory():
    item = seed_equipment.EQUIPMENT[0]
    data = from_row({"equipment_id": "x", **item}).to_dict()
    assert data["type"] == item["equipment_type"] and data["setupRequirements"]

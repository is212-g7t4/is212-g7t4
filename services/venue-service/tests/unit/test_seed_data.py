"""SCRUM-24 — the seed catalogue must have the same shape as live Supabase rows.

The seed script lives outside `app/`, so this checks its data rather than
contributing to `--cov=app`. It guards the SCRUM-114 bug where the seed wrote
status `Operational` and facilities as an array, neither of which matches the
live rows the UI actually reads.
"""
import importlib.util
from pathlib import Path

import pytest

SEED_PATH = Path(__file__).resolve().parents[2] / "scripts" / "seed_venues.py"
spec = importlib.util.spec_from_file_location("seed_venues", SEED_PATH)
seed_venues = importlib.util.module_from_spec(spec)
spec.loader.exec_module(seed_venues)

from app.models import serialize


@pytest.mark.parametrize("venue", seed_venues.VENUES, ids=lambda v: v["venue_name"])
def test_seed_venues_match_catalogue_shape(venue):
    """Every seed row uses the live status names, object facilities and list layouts."""
    assert venue["operational_status"] in seed_venues.STATUSES

    assert isinstance(venue["facilities"], dict)
    assert all(isinstance(enabled, bool) for enabled in venue["facilities"].values())

    assert isinstance(venue["supported_layouts"], list)
    assert all(isinstance(layout, str) for layout in venue["supported_layouts"])
    assert all(layout == layout.lower() for layout in venue["supported_layouts"])

    assert venue["venue_name"] and venue["location"] and venue["accessibility"]
    assert isinstance(venue["max_capacity"], int) and venue["max_capacity"] > 0


def test_seed_venue_names_are_unique():
    """The upsert keys on venue_name, so duplicates would silently overwrite."""
    names = [venue["venue_name"] for venue in seed_venues.VENUES]
    assert len(names) == len(set(names))


def test_seed_rows_survive_the_service_serializer():
    """A seeded row read back through the API produces a clean venue payload."""
    row = {
        "venue_id": "8381b11e-aaae-4d58-bdba-2607e9e2bde2",
        **{
            key: value
            for key, value in seed_venues.VENUES[0].items()
        },
    }

    venue = serialize(row)

    assert venue["facilities"] == sorted(
        key for key, enabled in seed_venues.VENUES[0]["facilities"].items() if enabled
    )
    assert venue["status"] in seed_venues.STATUSES

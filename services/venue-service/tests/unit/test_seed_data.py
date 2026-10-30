"""
SUPPORTING DESIGN CHECKS: Venue seed catalogue

User Story
----------
Supporting/supplementary design checks. No story or acceptance
criterion describes the behaviour these tests check; it is plumbing
that every story of this service relies on.

Real
----
- scripts/seed_venues.py's VENUES are loaded for real and passed through
  app.models.serialize().
- Assertions are on the seed rows' statuses, facilities and layouts shapes and
  name uniqueness.

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

SEED_PATH = Path(__file__).resolve().parents[2] / "scripts" / "seed_venues.py"
spec = importlib.util.spec_from_file_location("seed_venues", SEED_PATH)
seed_venues = importlib.util.module_from_spec(spec)
spec.loader.exec_module(seed_venues)

from app.models import serialize


# --- Supporting/supplementary design checks ----------------------------------
# No Jira acceptance criterion covers these. They check design decisions the
# stories rely on (health check, CORS, configuration and failure handling).


@pytest.mark.parametrize("venue", seed_venues.VENUES, ids=lambda v: v["venue_name"])
def test_seed_venue_when_loaded_matches_live_row_shape(venue):
    """
    Summary: Every seed venue uses the live status names, facilities object and layouts list.
    Supporting design check: the seed catalogue is valid catalogue data
    Double: None
    """
    assert venue["operational_status"] in seed_venues.STATUSES

    assert isinstance(venue["facilities"], dict)
    assert all(isinstance(enabled, bool) for enabled in venue["facilities"].values())

    assert isinstance(venue["supported_layouts"], list)
    assert all(isinstance(layout, str) for layout in venue["supported_layouts"])
    assert all(layout == layout.lower() for layout in venue["supported_layouts"])

    assert venue["venue_name"] and venue["location"] and venue["accessibility"]
    assert isinstance(venue["max_capacity"], int) and venue["max_capacity"] > 0


def test_seed_catalogue_when_loaded_has_unique_names():
    """
    Summary: No two seed venues share a name, so the upsert cannot overwrite one with another.
    Supporting design check: the seed catalogue is valid catalogue data
    Double: None
    """
    names = [venue["venue_name"] for venue in seed_venues.VENUES]
    assert len(names) == len(set(names))


def test_seed_row_when_serialized_gives_clean_venue():
    """
    Summary: A seed venue read back through the service gives a clean venue.
    Supporting design check: the seed catalogue is valid catalogue data
    Double: None
    """
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

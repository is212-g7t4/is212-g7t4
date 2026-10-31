"""
SCRUM-163: Review Event Safety Information

User Story
----------
As a Safety Officer, I want to see all of an event's safety-relevant
information in one place, so that I can assess its operational safety without
chasing other staff for details.

Acceptance Criteria
-------------------
AC1: Given a pending safety check, when I open it, then I see expected
     attendance against each venue's capacity, venue layout, emergency access
     details, accessibility requirements, equipment list with placement notes,
     crowd movement notes and known venue restrictions.
AC2: Given expected attendance exceeds a venue's capacity, then this is visibly
     flagged.
AC3: Given any of these items is not recorded, then it is shown as "Not
     provided".
AC4: Given the event has earlier safety decisions, then I can see each previous
     decision, its reason and the requested changes.
AC5: The review page is read-only: I cannot edit event, venue or equipment
     information from it.

Real
----
- An event's safety history for the Safety Officer: every round newest first,
  each with its decision, time, remarks and requested changes.
- We check the history returned.

Doubled
-------
- Safety records (database): hold the rounds each test needs, accept new ones,
  or cannot be reached [Stub]; we check what is saved, and that rounds are
  locked before they change [Mock].
- Sign-in: a test key signs the caller's token (tests/unit/conftest.py) [Stub].

Not proven
----------
- The review page that shows this history (-> safety-check-service SCRUM-163
  tests and the frontend).
"""

from unittest.mock import MagicMock

import pytest

from app import create_app
from tests.unit.factories import EVENT_ID, NEXT_RECORD_ID, OFFICER_ID, flag_row, record_row, signed_in


@pytest.fixture
def setup(monkeypatch):
    connection = MagicMock()
    cursor = connection.cursor.return_value.__enter__.return_value
    monkeypatch.setattr("app.models.psycopg2.connect", lambda *args, **kwargs: connection)
    app = create_app({"TESTING": True, "DATABASE_URL": "unused-test-url"})
    return signed_in(app.test_client(), OFFICER_ID, "Safety Officer"), cursor


def test_list_rounds_shows_each_previous_decision_newest_first(setup):
    """
    Summary: The Safety Officer sees each earlier round's decision, when it was made, its remarks and any requested changes, newest first.
    AC4: Given the event has earlier safety decisions, then I can see each
        previous decision, its reason and the requested changes.
    Double: The safety records hold a pending round and an earlier round where
        changes were requested in one area [Stub]; we check the rounds are
        asked for newest first [Mock].
    """
    client, cursor = setup
    cursor.fetchall.side_effect = [
        [
            record_row(round_number=2, status="Pending", safety_check_id=NEXT_RECORD_ID),
            record_row(round_number=1, status="Changes Requested", decided=True, remarks="Move the stage."),
        ],
        [flag_row()],
    ]

    response = client.get(f"/safety-check-records?eventId={EVENT_ID}")

    assert response.status_code == 200
    latest, earlier = response.json["safetyChecks"]
    assert [latest["roundNumber"], earlier["roundNumber"]] == [2, 1]
    assert earlier["status"] == "Changes Requested"
    assert earlier["decidedAt"] == "2026-11-02T03:00:00+00:00"
    assert earlier["remarks"] == "Move the stage."
    assert [flag["area"] for flag in earlier["flags"]] == ["venue arrangement"]
    assert latest["flags"] == []
    assert "ORDER BY round_number DESC" in cursor.execute.call_args_list[0].args[0]


def test_list_rounds_with_bad_event_id_returns_400(setup):
    """
    Summary: The history can only be shown for a valid event.
    AC4: Given the event has earlier safety decisions, then I can see each
        previous decision, its reason and the requested changes.
    Double: We check the safety records are never touched [Mock].
    """
    client, cursor = setup

    response = client.get("/safety-check-records?eventId=nope")

    assert response.status_code == 400
    assert response.json["message"] == "eventId must be a valid UUID."
    cursor.execute.assert_not_called()


# --- Supporting/supplementary design checks ----------------------------------
# No Jira acceptance criterion covers these. They check design decisions the
# stories rely on (health check, CORS, configuration and failure handling).


def test_list_rounds_when_database_url_missing_returns_503():
    """
    Summary: The history reports itself unavailable when no database is configured.
    Supporting design check: an unconfigured service answers 503
    Double: None
    """
    client = signed_in(create_app({"TESTING": True, "DATABASE_URL": None}).test_client(), OFFICER_ID, "Safety Officer")

    response = client.get(f"/safety-check-records?eventId={EVENT_ID}")

    assert response.status_code == 503

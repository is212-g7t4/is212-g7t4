"""SCRUM-163 Review Event Safety Information: Safety Check Record Service integration tests.

Story:      As a Safety Officer, I want to see all of an event's safety-relevant information in
            one place, so that I can assess its operational safety without chasing other staff
            for details.
Real:       Flask app and routes, token verification and the role check, app/models.py SQL
            (rounds newest first, flags joined per round), postgres:17.6 with the full migration
            chain.
Doubled:    nothing (Safety Check Record Service makes no outbound calls).
Not proven: how the review page lays the history out (Safety Check Service, frontend); Supabase
            sign-in itself (SCRUM-8).

AC1  Not covered here: attendance, venue and equipment details come from other atomics, via
     Safety Check Service.
AC2  Not covered here: the over-capacity flag is computed in Safety Check Service.
AC3  Not covered here: "Not provided" is applied in Safety Check Service and the frontend.
AC4  Given the event has earlier safety decisions, then I can see each previous decision, its
     reason and the requested changes.
AC5  Not covered here: the review page is read-only in the frontend.
"""

import pytest

from tests.integration.factories import (
    OFFICER_ID,
    as_user,
    make_event,
    make_flag,
    make_people,
    make_round,
)

pytestmark = [pytest.mark.integration, pytest.mark.enable_socket]

OFFICER = as_user(OFFICER_ID)


@pytest.fixture(autouse=True)
def people(db):
    make_people(db)


def history(client, event_id, query=""):
    return client.get(f"/safety-check-records?eventId={event_id}{query}", **OFFICER)


# AC4 ----

def test_ac4_every_earlier_decision_is_listed_with_its_reason_and_requested_changes(client, db):
    """Normal: newest first, and each round carries only its own flags."""
    event_id = make_event(db, status="Pending Safety Check")
    first = make_round(db, event_id, 1, status="Changes Requested", remarks="Too crowded.")
    make_flag(db, first, area="event details", change_required="Cap attendance at 60.")
    make_flag(db, first, area="venue arrangement", change_required="Open the side exit.")
    make_round(db, event_id, 2, status="Changes Requested", remarks="Cables across the aisle.")
    make_round(db, event_id, 3)
    other_event = make_event(db)
    make_round(db, other_event, status="Safety Rejected", remarks="Not this event.")

    response = history(client, event_id)

    rounds = response.get_json()["safetyChecks"]
    assert response.status_code == 200
    assert [(entry["roundNumber"], entry["status"], entry["remarks"]) for entry in rounds] == [
        (3, "Pending", None),
        (2, "Changes Requested", "Cables across the aisle."),
        (1, "Changes Requested", "Too crowded."),
    ]
    assert sorted((flag["area"], flag["changeRequired"]) for flag in rounds[2]["flags"]) == [
        ("event details", "Cap attendance at 60."),
        ("venue arrangement", "Open the side exit."),
    ]
    assert (rounds[0]["flags"], rounds[1]["flags"]) == ([], [])


def test_ac4_the_history_can_be_narrowed_to_one_decision_status(client, db):
    """Normal: the status filter runs in SQL and returns only the matching rounds."""
    event_id = make_event(db, status="Pending Safety Check")
    make_round(db, event_id, 1, status="Changes Requested", remarks="Too crowded.")
    make_round(db, event_id, 2)

    response = history(client, event_id, "&status=Changes%20Requested")

    assert [entry["roundNumber"] for entry in response.get_json()["safetyChecks"]] == [1]


def test_ac4_an_event_with_no_decisions_yet_has_an_empty_history(client, db):
    """Boundary: no rounds at all is an empty list, not an error."""
    event_id = make_event(db)

    response = history(client, event_id)

    assert (response.status_code, response.get_json()) == (200, {"safetyChecks": []})

"""
SCRUM-171: Reject Affected Bookings

User Story
----------
As a Venue Staff, I want the system to automatically reject existing venue
requests when I mark a venue as temporarily unavailable, so that I do not have
to manually reject each affected venue request.

Acceptance Criteria
-------------------
AC1: Given a closure is recorded, then requests for the same venue with
     overlapping booking intervals and status Pending, Pending Review, or
     Approved are changed to Rejected.
AC2: Given a request belongs to another venue, does not overlap the closure, or
     is already rejected or cancelled, then that request is not changed by the
     closure.
AC3: Given a request is rejected because of a closure, when its details are
     viewed, then the closure period and operational reason are displayed.
AC4: Given an affected venue request is rejected, the existing event itself or
     other venue requests under that event are not rejected and remain
     unchanged.

Real
----
- POST /venue-closures/preview (read-only impact: affected requests and a
  signed confirmation token) and POST /venue-closures (requires explicit
  confirmation bound to that exact impact and caller) run for real.
- Assertions are on the impact returned, the token checks and that a stale
  confirmation writes nothing.

Doubled
-------
- psycopg2.connect: Stub (`setup`/`client` fixtures) - fresh MagicMock
  connection; the cursor returns canned VenueBooking / VenueClosure rows (or
  raises); executed SQL, parameters and locks are inspected.

Not proven
----------
- That the SQL, locks and constraints behave the same on real PostgreSQL (->
  tests/integration/, throwaway postgres:17.6).
- That Venue Staff see the impact before confirming (-> frontend
  closureConfirmation.test.tsx).
"""

import pytest
from app import closure_store
from tests.unit.factories import bearer

DATA = dict(
    venueId="venue",
    startDateTime="2099-01-01T00:00:00+08:00",
    endDateTime="2099-01-02T00:00:00+08:00",
    reason="Maintenance",
)
KEY = "test-only-signing-key-not-a-production-default"


def test_preview_closure_returns_affected_requests_without_writing(setup):
    """
    Summary: Previewing a closure lists every request it would reject, without changing anything.
    AC1: Given a closure is recorded, then requests for the same venue with
        overlapping booking intervals and status Pending, Pending Review, or
        Approved are changed to Rejected.
    AC2: Given a request belongs to another venue, does not overlap the
        closure, or is already rejected or cancelled, then that request is not
        changed by the closure.
    Double: Stub (cursor returns affected rows), Mock (no write)
    """
    # Arrange (Given)
    from tests.unit.factories import VENUE_ID, USER_ID, booking_row

    client, cursor = setup
    client.application.config.update(
        CLOSURE_CONFIRMATION_KEY=KEY
    )
    cursor.fetchall.return_value = [booking_row()]

    # Act (When)
    response = client.post(
        "/venue-closures/preview",
        json=DATA | {"venueId": VENUE_ID},
        headers=bearer(USER_ID, "Venue Staff"),
    )

    # Assert (Then)
    assert response.status_code == 200
    assert response.json["affectedCount"] == 1
    assert response.json["affectedRequests"][0]["eventId"]
    assert response.json["confirmationToken"]
    assert all(
        call.args[0].lstrip().startswith("SELECT")
        for call in cursor.execute.call_args_list
    )


@pytest.fixture(autouse=True)
def fixed_confirmation_clock(monkeypatch):
    # Token validity must not depend on wall-clock rollover or machine time.
    monkeypatch.setattr("time.time", lambda: 1_800_000_000)


@pytest.mark.parametrize(
    "token",
    [None, "", "bad", "1800000900.bad"],
    ids=["missing", "empty", "malformed", "tampered-signature"],
)
def test_create_closure_with_invalid_or_expired_token_requires_reconfirmation(token):
    """
    Summary: A bad or expired confirmation must be redone before the closure is saved.
    AC1: Given a closure is recorded, then requests for the same venue with
        overlapping booking intervals and status Pending, Pending Review, or
        Approved are changed to Rejected.
    Double: Stub (cursor)
    """
    # Arrange (Given): token, from fixtures

    # Act + Assert (When / Then)
    with pytest.raises(closure_store.PreviewChangedError):
        closure_store.verify_preview(token, DATA, "staff", [], KEY)


@pytest.mark.parametrize(
    "expires", [1_800_000_000, 1_800_000_901], ids=["expired", "beyond-validity-window"]
)
def test_create_closure_with_token_outside_validity_window_requires_reconfirmation(expires):
    """
    Summary: A confirmation used outside its time window must be redone.
    AC1: Given a closure is recorded, then requests for the same venue with
        overlapping booking intervals and status Pending, Pending Review, or
        Approved are changed to Rejected.
    Double: Stub (cursor)
    """
    # Arrange (Given)
    token = closure_store.sign_preview(DATA, "staff", [], KEY, expires=expires)

    # Act + Assert (When / Then)
    with pytest.raises(closure_store.PreviewChangedError):
        closure_store.verify_preview(token, DATA, "staff", [], KEY)


@pytest.mark.parametrize("path", ["/venue-closures", "/venue-closures/preview"], ids=["create", "preview"])
@pytest.mark.parametrize("key", [None, "short", 123], ids=["missing", "too_short", "not_text"])
def test_closure_routes_without_signing_key_are_unavailable(setup, path, key):
    """
    Summary: Without a proper signing key, closures cannot be previewed or confirmed.
    AC1: Given a closure is recorded, then requests for the same venue with
        overlapping booking intervals and status Pending, Pending Review, or
        Approved are changed to Rejected.
    Double: None
    """
    # Arrange (Given)
    from tests.unit.factories import VENUE_ID, USER_ID

    client, cursor = setup
    client.application.config.update(
        CLOSURE_CONFIRMATION_KEY=key
    )
    data = DATA | {"venueId": VENUE_ID}
    if path == "/venue-closures":
        data |= dict(confirmed=True, confirmationToken="invalid")

    # Act (When)
    response = client.post(
        path, json=data, headers=bearer(USER_ID, "Venue Staff")
    )

    # Assert (Then)
    assert response.status_code == 503
    cursor.execute.assert_not_called()


@pytest.mark.parametrize(
    "extra",
    [
        {},
        {"confirmed": False},
        {"confirmed": True},
        {"confirmed": True, "confirmationToken": 123},
        {"confirmed": True, "confirmationToken": "x" * 257},
    ],
    ids=["no_confirmation", "confirmed_false", "confirmed_without_token", "wrong_token", "malformed_token"],
)
def test_create_closure_without_explicit_confirmation_is_refused(setup, extra):
    """
    Summary: A closure is saved only with an explicit, valid confirmation.
    AC1: Given a closure is recorded, then requests for the same venue with
        overlapping booking intervals and status Pending, Pending Review, or
        Approved are changed to Rejected.
    Double: Stub (cursor)
    """
    # Arrange (Given)
    from tests.unit.factories import VENUE_ID, USER_ID

    client, cursor = setup
    client.application.config.update(
        CLOSURE_CONFIRMATION_KEY=KEY
    )

    # Act (When)
    response = client.post(
        "/venue-closures",
        json=DATA | {"venueId": VENUE_ID} | extra,
        headers=bearer(USER_ID, "Venue Staff"),
    )

    # Assert (Then)
    assert response.status_code == 400
    cursor.execute.assert_not_called()


def test_closure_when_preview_fails_or_impact_changed_writes_nothing(setup):
    """
    Summary: If the preview fails or the impact changed since confirming, nothing is written.
    AC1: Given a closure is recorded, then requests for the same venue with
        overlapping booking intervals and status Pending, Pending Review, or
        Approved are changed to Rejected.
    AC4: Given an affected venue request is rejected, the existing event itself
        or other venue requests under that event are not rejected and remain
        unchanged.
    Double: Stub (cursor raises or returns a changed impact), Mock (no write)
    """
    # Arrange (Given)
    import psycopg2
    from tests.unit.factories import VENUE_ID, USER_ID

    client, cursor = setup
    client.application.config.update(
        CLOSURE_CONFIRMATION_KEY=KEY
    )
    headers = bearer(USER_ID, "Venue Staff")

    # Act + Assert (When / Then)
    assert (
        client.post("/venue-closures/preview", json={}, headers=headers).status_code
        == 400
    )
    cursor.execute.side_effect = psycopg2.OperationalError()
    assert (
        client.post(
            "/venue-closures/preview",
            json=DATA | {"venueId": VENUE_ID},
            headers=headers,
        ).status_code
        == 503
    )
    cursor.execute.side_effect = None
    response = client.post(
        "/venue-closures",
        json=DATA
        | {"venueId": VENUE_ID, "confirmed": True, "confirmationToken": "invalid"},
        headers=headers,
    )
    assert response.status_code == 409
    assert response.json["code"] == "CLOSURE_PREVIEW_CHANGED"
    assert not any(
        "INSERT" in c.args[0] or "UPDATE public" in c.args[0]
        for c in cursor.execute.call_args_list
    )


def test_closure_confirmation_is_bound_to_impact_and_caller():
    """
    Summary: A confirmation only works for the exact impact and the staff member who previewed it.
    AC1: Given a closure is recorded, then requests for the same venue with
        overlapping booking intervals and status Pending, Pending Review, or
        Approved are changed to Rejected.
    Double: Stub (cursor)
    """
    rows = [dict(id="booking", status="Pending Review", start="09:00", end="10:00")]
    token = closure_store.sign_preview(DATA, "staff", rows, KEY)
    closure_store.verify_preview(token, DATA, "staff", rows, KEY)
    for data, staff, impact in [
        (DATA | {"reason": "other"}, "staff", rows),
        (DATA, "other", rows),
        (DATA, "staff", []),
        (DATA, "staff", [rows[0] | {"status": "Approved"}]),
        (DATA, "staff", [rows[0] | {"start": "08:00"}]),
    ]:
        with pytest.raises(closure_store.PreviewChangedError):
            closure_store.verify_preview(token, data, staff, impact, KEY)

"""Shared ids and row builders for the Venue Availability unit tests.

These used to live in test_bookings.py and were imported from there by the
other test modules. A test module should never import another test module, so
they live here instead.
"""

import time

import jwt
from cryptography.hazmat.primitives.asymmetric import ec

from datetime import datetime

EVENT_ID = "00000000-0000-0000-0000-0000000000e1"
VENUE_ID = "00000000-0000-0000-0000-0000000000f1"
USER_ID = "00000000-0000-0000-0000-000000000001"
BOOKING_ID = "00000000-0000-0000-0000-00000000000b"


def booking_row(**overrides):
    row = {
        "booking_id": BOOKING_ID,
        "event_id": EVENT_ID,
        "venue_id": VENUE_ID,
        "requested_start_time": datetime(2026, 10, 1, 9),
        "requested_end_time": datetime(2026, 10, 1, 12),
        "required_capacity": 80,
        "venue_requirements": "Projector and movable seating",
        "status": "Pending Review",
        "requested_by": USER_ID,
        "reviewed_by": None,
    }
    row.update(overrides)
    return row


def assert_booking_intent(cursor, kind, source):
    """SCRUM-47: one exact intent follows the mutation in its successful transaction.

    The driver is doubled: this verifies SQL intent and ordering, not durable commit.
    PostgreSQL integration reads the committed row independently.
    """
    writes = [call.args for call in cursor.execute.call_args_list
              if 'INSERT INTO public."VenueNotificationOutbox"' in call.args[0]]
    assert len(writes) == 1
    sql, (actual_kind, booking_id, payload) = writes[0]
    assert actual_kind == kind
    assert str(booking_id) == source["bookingId"]
    assert payload.adapted == source
    assert "(type,booking_id,source) VALUES (%s,%s,%s)" in sql
    assert cursor.execute.call_args.args == writes[0]
    connection = cursor.connection
    assert connection.cursor.return_value.__enter__.return_value is cursor
    connection.__enter__.assert_called_once()
    connection.__exit__.assert_called_once_with(None, None, None)
    connection.commit.assert_not_called()  # No intermediate commit separates mutation and intent.
    connection.rollback.assert_not_called()
    calls = connection.mock_calls
    entered = next(i for i, call in enumerate(calls) if call[0] == '__enter__')
    mutation = next(i for i, call in enumerate(calls)
                    if call[0].endswith('.execute') and
                    ('INSERT INTO public."VenueBooking"' in call.args[0] or
                     'UPDATE public."VenueBooking"' in call.args[0]))
    intent = next(i for i, call in enumerate(calls)
                  if call[0].endswith('.execute') and 'VenueNotificationOutbox' in call.args[0])
    committed = next(i for i, call in enumerate(calls) if call[0] == '__exit__')
    assert entered < mutation < intent < committed


def assert_no_booking_intent(cursor):
    """SCRUM-47 supporting rule: refused mutations schedule no notification."""
    assert not any('INSERT INTO public."VenueNotificationOutbox"' in call.args[0]
                   for call in cursor.execute.call_args_list)


# Stands in for Supabase's ES256 signing key; the unit conftest makes the
# verifier trust its public half (SCRUM-8).
TEST_SIGNING_KEY = ec.generate_private_key(ec.SECP256R1())


def bearer(user_id, role, key=TEST_SIGNING_KEY, **claims):
    """Authorization header for a signed-in user, as Supabase would issue it."""
    payload = {"sub": user_id, "aud": "authenticated", "exp": int(time.time()) + 3600, "user_role": role}
    payload.update(claims)
    return {"Authorization": f"Bearer {jwt.encode(payload, key, algorithm='ES256')}"}


def signed_in(client, user_id=USER_ID, role="Event Coordinator"):
    """Send every request from this test client with a signed-in user's token."""
    client.environ_base["HTTP_AUTHORIZATION"] = bearer(user_id, role)["Authorization"]
    return client

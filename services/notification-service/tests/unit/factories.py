"""Independent synthetic SCRUM-49 wire examples and unit boundary recorder."""

import time

import jwt
from cryptography.hazmat.primitives.asymmetric import ec
from unittest.mock import MagicMock, Mock, patch
import json

EVENT = "30000000-0000-4000-8000-000000000001"
REQUEST = "40000000-0000-4000-8000-000000000001"
RECIPIENT = "10000000-0000-4000-8000-000000000001"
OTHER = "10000000-0000-4000-8000-000000000002"


def make_change_envelope(kind="submitted", **detail_overrides):
    """Build wire content independently of production formatting and other test modules."""
    details = dict(eventId=EVENT, eventName="Workshop", recipientId=RECIPIENT)
    destination = dict(kind="event-details", eventId=EVENT)
    if kind != "cancelled":
        details["changeRequestId"] = REQUEST
    if kind == "submitted":
        details["proposedChanges"] = dict(eventName="New Workshop", expectedAttendance="40")
        destination.update(kind="change-request-review", changeRequestId=REQUEST)
        message = "Change requested for Workshop. Proposed changes: Event Name: New Workshop; Expected Attendance: 40."
    elif kind == "approved":
        details.update(decision="Approved", previousEventName="Original Workshop")
        message = "Change request for Workshop (formerly Original Workshop) was approved."
    elif kind == "rejected":
        details.update(decision="Rejected", reason="Keep accessible transport.\n交通安排需完善。")
        message = "Change request for Workshop was rejected: " + details["reason"]
    else:
        message = "Workshop was cancelled."
    details.update(detail_overrides)
    return dict(version=1, id="50000000-0000-4000-8000-000000000001",
                recipientId=RECIPIENT, type="event.cancelled" if kind == "cancelled" else "event.change-request-" + kind,
                createdAt="2030-01-01T00:00:00+00:00", message=message,
                destination=destination, details=details)


def process_change_at_sql_boundary(envelope, *, quarantined=False, error=None):
    """Run real parse/process/store SQL; fake only libpq connection and broker ACK.

    At ACK require exact insert content, completed transaction exit and closed
    connection. A SQL mock proves the write contract, not actual DB persistence.
    Return the observed ordered outcome for an explicit assertion in each test.
    """
    from app.consumer import process

    connection, channel = MagicMock(), Mock()
    cursor = connection.cursor.return_value.__enter__.return_value
    body = json.dumps(envelope).encode()
    observed = []

    def acknowledge(*, delivery_tag):
        assert delivery_tag == 7
        cursor.execute.assert_called_once()
        sql, params = cursor.execute.call_args.args
        if quarantined:
            assert 'INSERT INTO public."NotificationFailure"' in sql
            assert bytes(params[0].adapted) == body
            if error is not None:
                assert params[1] == error
            observed.append("quarantined")
        else:
            assert 'INSERT INTO public."Notification" ' in sql
            assert params[:5] == (envelope["id"], envelope["id"], envelope["recipientId"], envelope["type"], EVENT)
            assert params[5].adapted == envelope
            assert params[6:] == (envelope["id"], envelope["createdAt"])
            observed.append("stored")
        # The real store transaction has exited normally and released its connection.
        connection.__exit__.assert_called_once_with(None, None, None)
        connection.close.assert_called_once_with()
        observed.append("acknowledged")

    channel.basic_ack.side_effect = acknowledge
    with patch("psycopg2.connect", return_value=connection):
        process("unused", channel, Mock(delivery_tag=7), body)
    channel.basic_ack.assert_called_once_with(delivery_tag=7)
    return observed


def attendee_envelope(kind="registration.confirmed"):
    """Return independent attendee wire content for parser acceptance/refusal checks.
    The requested type shares fixed UUID identities and registration-only navigation.
    Extra display fields allow focused mutations; generic message text is deliberately
    not a claim that the production formatter generated this complete envelope.
    """
    ref="33333333-3333-4333-8333-333333333333"
    return dict(version=1,id="44444444-4444-4444-8444-444444444444",type=kind,
        recipientId="22222222-2222-4222-8222-222222222222",createdAt="2030-01-01T00:00:00+00:00",
        message="Workshop notification.",destination=dict(kind="attendee-registration",registrationId=ref),
        details=dict(eventId="11111111-1111-4111-8111-111111111111",eventName="Workshop",registrationId=ref,
                     startDateTime="2030-03-01T01:00:00+00:00",endDateTime="2030-03-01T09:00:00+00:00",venueName="Hall A",
                     changes={"venueName":["Hall A","Hall C"]}))


# Stands in for Supabase's ES256 signing key; the unit conftest makes the
# verifier trust its public half (SCRUM-8).
TEST_SIGNING_KEY = ec.generate_private_key(ec.SECP256R1())


def bearer(user_id, role, key=TEST_SIGNING_KEY, **claims):
    """Authorization header for a signed-in user, as Supabase would issue it."""
    payload = {"sub": user_id, "aud": "authenticated", "exp": int(time.time()) + 3600, "user_role": role}
    payload.update(claims)
    return {"Authorization": f"Bearer {jwt.encode(payload, key, algorithm='ES256')}"}


def signed_in(client, user_id="00000000-0000-4000-8000-000000000001", role="Event Coordinator"):
    """Send every request from this test client with a signed-in user's token."""
    client.environ_base["HTTP_AUTHORIZATION"] = bearer(user_id, role)["Authorization"]
    return client

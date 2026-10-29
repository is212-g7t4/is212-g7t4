"""# Test scope and acceptance mapping — SCRUM-171 integration

- **SCRUM-171 AC4 backend support:** read-only impact/count/token, explicit confirmation gate and changed-impact no-write refusal.
- **Supporting security/configuration:** signed exact input/identity/impact binding, genuine fixed-clock expiry, malformed signatures and missing keys. No complete visual-preview or transaction proof.

## Case/group traceability

- `test_read_only_preview_route_returns_complete_impact`: AC4 backend partial support — read-only preview count, event ID and confirmation token; SELECT-only calls (not complete visual/name assertions).
- `test_invalid_or_expired_token_requires_reconfirmation`: Supporting AC4 confirmation integrity — invalid/expired tokens raise PreviewChangedError; not visible reconfirmation.
- `test_signed_token_outside_validity_window_requires_reconfirmation`: Supporting AC4 confirmation validity: genuinely signed expired/out-of-window tokens rejected using a fixed clock; not a new functional acceptance case.
- `test_key_is_required_without_default`: Infrastructure/configuration support — missing/invalid signing key returns 503; no direct AC.
- `test_create_requires_explicit_confirmation`: AC4 backend confirmation gate — missing/false/malformed explicit confirmation returns 400; no browser claim.
- `test_preview_failure_and_stale_confirmation_write_nothing`: AC4 backend changed-impact clause — stale confirmation returns 409 without INSERT/UPDATE; preview-error handling supporting.
- `test_confirmation_binds_exact_impact_and_caller`: Supporting AC4 signed binding — exact impact, input and caller mismatch rejected; not user-visible review.

## Existing test contract and detailed cases

SCRUM-171 AC4: signed preview binds inputs, identity and exact impact.

Missing-key checks are supporting configuration safety, not direct acceptance.
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


def test_read_only_preview_route_returns_complete_impact(setup):
    from tests.unit.factories import VENUE_ID, USER_ID, booking_row

    client, cursor = setup
    client.application.config.update(
        CLOSURE_CONFIRMATION_KEY=KEY
    )
    cursor.fetchall.return_value = [booking_row()]
    response = client.post(
        "/venue-closures/preview",
        json=DATA | {"venueId": VENUE_ID},
        headers=bearer(USER_ID, "Venue Staff"),
    )
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
def test_invalid_or_expired_token_requires_reconfirmation(token):
    with pytest.raises(closure_store.PreviewChangedError):
        closure_store.verify_preview(token, DATA, "staff", [], KEY)


@pytest.mark.parametrize(
    "expires", [1_800_000_000, 1_800_000_901], ids=["expired", "beyond-validity-window"]
)
def test_signed_token_outside_validity_window_requires_reconfirmation(expires):
    token = closure_store.sign_preview(DATA, "staff", [], KEY, expires=expires)
    with pytest.raises(closure_store.PreviewChangedError):
        closure_store.verify_preview(token, DATA, "staff", [], KEY)


@pytest.mark.parametrize("path", ["/venue-closures", "/venue-closures/preview"])
@pytest.mark.parametrize("key", [None, "short", 123])
def test_key_is_required_without_default(setup, path, key):
    from tests.unit.factories import VENUE_ID, USER_ID

    client, cursor = setup
    client.application.config.update(
        CLOSURE_CONFIRMATION_KEY=key
    )
    data = DATA | {"venueId": VENUE_ID}
    if path == "/venue-closures":
        data |= dict(confirmed=True, confirmationToken="invalid")
    response = client.post(
        path, json=data, headers=bearer(USER_ID, "Venue Staff")
    )
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
)
def test_create_requires_explicit_confirmation(setup, extra):
    from tests.unit.factories import VENUE_ID, USER_ID

    client, cursor = setup
    client.application.config.update(
        CLOSURE_CONFIRMATION_KEY=KEY
    )
    response = client.post(
        "/venue-closures",
        json=DATA | {"venueId": VENUE_ID} | extra,
        headers=bearer(USER_ID, "Venue Staff"),
    )
    assert response.status_code == 400
    cursor.execute.assert_not_called()


def test_preview_failure_and_stale_confirmation_write_nothing(setup):
    import psycopg2
    from tests.unit.factories import VENUE_ID, USER_ID

    client, cursor = setup
    client.application.config.update(
        CLOSURE_CONFIRMATION_KEY=KEY
    )
    headers = bearer(USER_ID, "Venue Staff")
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


def test_confirmation_binds_exact_impact_and_caller():
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

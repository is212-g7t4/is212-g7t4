import pytest
from flask.testing import FlaskClient
from unittest.mock import MagicMock

from app import create_app
from tests.unit.factories import EVENT_ID, MIC, ORIGIN, TABLE


@pytest.fixture
def setup(monkeypatch):
    """A real app over a doubled database: returns (client, cursor, connect).

    cursor is a Stub (set fetchone/fetchall); connect is a Mock (assert it was
    or was not called). Requests enter as Equipment Reservation Service would
    send them: with the internal token and a notification context naming no
    recipients (unless the test sends its own), so SCRUM-32/33 tests see no
    notification side effects.
    """
    connection = MagicMock()
    cursor = connection.cursor.return_value.__enter__.return_value
    connect = MagicMock(return_value=connection)
    monkeypatch.setattr("app.models.psycopg2.connect", connect)

    class CompositeClient(FlaskClient):
        def open(self, *args, **kwargs):
            payload = kwargs.get("json")
            if isinstance(payload, dict):
                kwargs["json"] = {"notificationContext": {
                    "eventId": EVENT_ID, "eventName": "Fixture event", "recipientIds": [],
                    "coordinatorId": None, "equipmentNames": {MIC: "Microphone", TABLE: "Table"}}, **payload}
                kwargs["headers"] = {**kwargs.get("headers", {}), "X-Internal-Token": "synthetic"}
            return super().open(*args, **kwargs)

    app = create_app({"DATABASE_URL": "postgresql://x", "FRONTEND_ORIGIN": ORIGIN,
                      "INTERNAL_SERVICE_TOKEN": "synthetic"})
    app.test_client_class = CompositeClient
    return app.test_client(), cursor, connect

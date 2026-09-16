from app import create_app
from app.clients import MOCK_COORDINATORS


class FakeEventServiceResponse:
    def __init__(self, event_id, coordinator_id):
        self.event_id = event_id
        self.coordinator_id = coordinator_id

    def raise_for_status(self):
        return None

    def json(self):
        return {
            "id": self.event_id,
            "coordinatorId": self.coordinator_id,
        }


def test_assignment_and_reassignment_forward_updates_to_event_service(monkeypatch):
    """The assignment endpoint forwards both initial and replacement assignments."""
    requests = []

    def fake_patch(url, json):
        requests.append((url, json))
        return FakeEventServiceResponse(
            url.rsplit("/", 1)[-1], json["assignedCoordinatorId"]
        )

    monkeypatch.setattr("app.clients.httpx.patch", fake_patch)
    client = create_app().test_client()
    event_id = "4a569df8-b7e4-44a2-af9f-d6039c0191e7"
    first_coordinator = MOCK_COORDINATORS[0]["user_id"]
    replacement_coordinator = MOCK_COORDINATORS[1]["user_id"]

    assigned = client.post(
        f"/events/{event_id}/assign-coordinator/{first_coordinator}"
    )
    reassigned = client.post(
        f"/events/{event_id}/assign-coordinator/{replacement_coordinator}"
    )

    assert assigned.status_code == 200
    assert reassigned.status_code == 200
    assert requests == [
        (
            f"http://localhost:5003/events/{event_id}",
            {"assignedCoordinatorId": first_coordinator},
        ),
        (
            f"http://localhost:5003/events/{event_id}",
            {"assignedCoordinatorId": replacement_coordinator},
        ),
    ]
    assert reassigned.json["coordinatorId"] == replacement_coordinator
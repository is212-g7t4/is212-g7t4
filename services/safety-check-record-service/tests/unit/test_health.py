from app import create_app
from tests.unit.factories import signed_in


def test_health():
    client = signed_in(create_app().test_client())
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json == {"status": "ok"}

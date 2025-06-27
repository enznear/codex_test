from fastapi.testclient import TestClient
from backend.main import app


def test_status_returns_200():
    with TestClient(app) as client:
        response = client.get("/status")
        assert response.status_code == 200

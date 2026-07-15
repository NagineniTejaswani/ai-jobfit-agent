import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch
from app.main import app

client = TestClient(app)


def test_health_check():
    """The root endpoint should confirm the server is alive."""
    response = client.get("/")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_analyze_rejects_empty_message():
    """An empty message should be rejected by Pydantic validation before reaching the agent."""
    response = client.post("/analyze", json={"message": "", "resume": "Valid resume text " * 5})
    assert response.status_code == 422


def test_analyze_rejects_too_short_message():
    """A message under 5 characters should be rejected by Pydantic validation."""
    response = client.post("/analyze", json={"message": "hi", "resume": "Valid resume text " * 5})
    assert response.status_code == 422


def test_analyze_rejects_short_resume():
    """A resume under 50 characters should be rejected by Pydantic validation."""
    response = client.post("/analyze", json={"message": "Find me a backend job", "resume": "short"})
    assert response.status_code == 422


def test_analyze_missing_field_returns_422():
    """Sending a request with no 'message' field at all should fail FastAPI's own validation."""
    response = client.post("/analyze", json={})
    assert response.status_code == 422  # FastAPI's built-in Pydantic validation error


def test_history_returns_a_list():
    """/history should always return a list, even if empty."""
    response = client.get("/history")
    assert response.status_code == 200
    assert isinstance(response.json(), list)
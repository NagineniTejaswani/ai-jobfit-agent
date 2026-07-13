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
    """An empty message should be rejected before any LLM call happens."""
    response = client.post("/analyze", json={"message": ""})
    assert response.status_code == 200
    assert response.json()["status"] == "invalid_input"


def test_analyze_rejects_too_short_message():
    """A message under 5 characters should be rejected."""
    response = client.post("/analyze", json={"message": "hi"})
    assert response.status_code == 200
    assert response.json()["status"] == "invalid_input"


def test_analyze_missing_field_returns_422():
    """Sending a request with no 'message' field at all should fail FastAPI's own validation."""
    response = client.post("/analyze", json={})
    assert response.status_code == 422  # FastAPI's built-in Pydantic validation error


def test_history_returns_a_list():
    """/history should always return a list, even if empty."""
    response = client.get("/history")
    assert response.status_code == 200
    assert isinstance(response.json(), list)
import pytest
from unittest.mock import patch, Mock
from app.tools import search_jobs, get_job_details


def test_search_jobs_returns_list_of_dicts():
    """search_jobs should return a list of jobs with expected keys, using a fake API response."""
    fake_response = {
        "jobs": [
            {"id": 123, "title": "Backend Engineer", "company_name": "TestCo", "url": "http://example.com/123"},
            {"id": 456, "title": "Frontend Engineer", "company_name": "TestCo2", "url": "http://example.com/456"},
        ]
    }

    with patch("app.tools.requests.get") as mock_get:
        mock_get.return_value.json.return_value = fake_response
        results = search_jobs("backend")

    assert isinstance(results, list)
    assert len(results) == 2
    assert results[0]["id"] == 123
    assert results[0]["title"] == "Backend Engineer"
    assert "company" in results[0]
    assert "url" in results[0]


def test_search_jobs_limits_to_5_results():
    """Even if the API returns more than 5 jobs, search_jobs should only return 5."""
    fake_jobs = [{"id": i, "title": f"Job {i}", "company_name": "Co", "url": "http://x.com"} for i in range(10)]

    with patch("app.tools.requests.get") as mock_get:
        mock_get.return_value.json.return_value = {"jobs": fake_jobs}
        results = search_jobs("anything")

    assert len(results) == 5


def test_get_job_details_finds_matching_job():
    """get_job_details should return the job matching the given id."""
    fake_response = {
        "jobs": [
            {"id": 123, "title": "Backend Engineer", "company_name": "TestCo",
             "description": "A great job", "tags": ["python", "fastapi"]},
        ]
    }

    with patch("app.tools.requests.get") as mock_get:
        mock_get.return_value.json.return_value = fake_response
        result = get_job_details(123)

    assert result["id"] == 123
    assert result["title"] == "Backend Engineer"
    assert result["tags"] == ["python", "fastapi"]


def test_get_job_details_returns_error_for_missing_id():
    """get_job_details should return a clear error if the job id doesn't exist."""
    fake_response = {"jobs": [{"id": 123, "title": "Backend Engineer", "company_name": "TestCo",
                                "description": "desc", "tags": []}]}

    with patch("app.tools.requests.get") as mock_get:
        mock_get.return_value.json.return_value = fake_response
        result = get_job_details(999)  # doesn't exist

    assert "error" in result
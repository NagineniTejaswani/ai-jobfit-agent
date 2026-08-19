import pytest
from unittest.mock import patch
from app.tools import search_jobs, get_job_details


def test_search_jobs_returns_list_of_dicts():
    """search_jobs should return a list of jobs with expected keys, using a fake API response."""
    fake_response = {
        "jobs": [
            {"id": 123, "jobTitle": "Backend Engineer", "companyName": "TestCo", "url": "http://example.com/123", "jobDescription": "Python FastAPI", "jobTags": ["python"]},
            {"id": 456, "jobTitle": "Frontend Engineer", "companyName": "TestCo2", "url": "http://example.com/456", "jobDescription": "React JS", "jobTags": ["react"]},
        ]
    }

    with patch("app.tools.requests.get") as mock_get:
        mock_get.return_value.json.return_value = fake_response
        results = search_jobs("backend")

    assert isinstance(results, list)
    assert len(results) == 2
    assert results[0]["id"] == 123
    assert results[0]["title"] == "Backend Engineer"
    assert results[0]["company"] == "TestCo"
    assert "url" in results[0]
    assert "description" in results[0]
    assert "full_description" in results[0]


def test_search_jobs_handles_empty_response():
    """search_jobs should return an empty list gracefully when API returns no jobs."""
    with patch("app.tools.requests.get") as mock_get:
        mock_get.return_value.json.return_value = {"jobs": []}
        results = search_jobs("nonexistentjob")

    assert isinstance(results, list)


def test_get_job_details_returns_dict():
    """get_job_details should return a dict with the given job id."""
    result = get_job_details(123)
    assert isinstance(result, dict)
    assert result["id"] == 123
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


def test_extract_pdf_rejects_non_pdf():
    """Uploading non-PDF file should return 400."""
    response = client.post(
        "/extract-pdf",
        files={"file": ("resume.txt", b"Hello world text", "text/plain")}
    )
    assert response.status_code == 400
    assert "Only PDF files are supported" in response.json()["detail"]


def test_extract_pdf_rejects_empty_file():
    """Uploading empty PDF should return 400."""
    response = client.post(
        "/extract-pdf",
        files={"file": ("resume.pdf", b"", "application/pdf")}
    )
    assert response.status_code == 400
    assert "empty" in response.json()["detail"]


def test_extract_pdf_success():
    """Uploading a valid PDF should extract text and return filename and char_count."""
    # pyrefly: ignore [missing-import]
    from pypdf import PdfWriter
    import io

    writer = PdfWriter()
    page = writer.add_blank_page(width=200, height=200)
    # We can mock extract_text_from_pdf to return resume text
    with patch("app.main.extract_text_from_pdf", return_value="Senior Software Engineer with 5 years experience in Python and React"):
        pdf_bytes = io.BytesIO()
        writer.write(pdf_bytes)
        pdf_bytes.seek(0)

        response = client.post(
            "/extract-pdf",
            files={"file": ("my_resume.pdf", pdf_bytes.read(), "application/pdf")}
        )
        assert response.status_code == 200
        data = response.json()
        assert data["filename"] == "my_resume.pdf"
        assert "Senior Software Engineer" in data["text"]
        assert data["char_count"] > 0

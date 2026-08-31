import pytest
import io
from fastapi import HTTPException
# pyrefly: ignore [missing-import]
from pypdf import PdfWriter
from app.pdf_utils import extract_text_from_pdf


def test_extract_text_empty_bytes():
    with pytest.raises(HTTPException) as exc_info:
        extract_text_from_pdf(b"")
    assert exc_info.value.status_code == 400
    assert "empty" in exc_info.value.detail


def test_extract_text_corrupt_bytes():
    with pytest.raises(HTTPException) as exc_info:
        extract_text_from_pdf(b"not a valid pdf content")
    assert exc_info.value.status_code == 400
    assert "Could not read PDF" in exc_info.value.detail


def test_extract_text_blank_pdf():
    writer = PdfWriter()
    writer.add_blank_page(width=100, height=100)
    buf = io.BytesIO()
    writer.write(buf)
    buf.seek(0)

    with pytest.raises(HTTPException) as exc_info:
        extract_text_from_pdf(buf.read())
    assert exc_info.value.status_code == 400
    assert "No readable text" in exc_info.value.detail

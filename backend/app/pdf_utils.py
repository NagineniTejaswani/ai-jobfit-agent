import io
from fastapi import HTTPException
# pyrefly: ignore [missing-import]
from pypdf import PdfReader


def extract_text_from_pdf(file_bytes: bytes) -> str:
    """Extract and concatenate text from all pages of an uploaded PDF file."""
    if not file_bytes:
        raise HTTPException(status_code=400, detail="Uploaded file is empty.")

    try:
        reader = PdfReader(io.BytesIO(file_bytes))
    except Exception as e:
        raise HTTPException(
            status_code=400,
            detail=f"Could not read PDF. The file may be corrupt or encrypted: {str(e)}"
        )

    if len(reader.pages) == 0:
        raise HTTPException(status_code=400, detail="The PDF file contains no pages.")

    extracted_pages = []
    for page_idx, page in enumerate(reader.pages):
        try:
            page_text = page.extract_text()
            if page_text and page_text.strip():
                extracted_pages.append(page_text.strip())
        except Exception:
            continue

    full_text = "\n\n".join(extracted_pages).strip()

    if not full_text:
        raise HTTPException(
            status_code=400,
            detail=(
                "No readable text could be extracted from this PDF. "
                "It may be a scanned image or photo. Please paste your resume text or upload a text-based PDF."
            )
        )

    return full_text

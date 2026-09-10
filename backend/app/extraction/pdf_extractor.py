"""PyMuPDF-based PDF text extraction + page rendering (for the scanned/OCR
fallback path).
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from io import BytesIO

import fitz  # PyMuPDF
from PIL import Image


class InvalidPDFError(Exception):
    pass


@dataclass
class ExtractedText:
    text: str
    page_count: int
    is_meaningful: bool


def _meaningful_char_ratio(text: str) -> float:
    stripped = text.strip()
    if not stripped:
        return 0.0
    alnum = sum(1 for c in stripped if c.isalnum())
    return alnum / max(len(stripped), 1)


def extract_text(pdf_bytes: bytes, *, min_length_for_digital: int) -> ExtractedText:
    """Extract text from every page using PyMuPDF.

    A PDF is considered to have "meaningful text" if the extracted text is
    at least `min_length_for_digital` characters long AND is mostly
    alphanumeric (guards against PDFs whose only "text" is stray artifacts).
    """
    try:
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    except Exception as exc:  # PyMuPDF raises a variety of low-level errors
        raise InvalidPDFError(f"Could not open file as a PDF: {exc}") from exc

    if doc.page_count == 0:
        raise InvalidPDFError("PDF has no pages.")

    pages_text = [page.get_text("text") for page in doc]
    full_text = "\n".join(pages_text)
    page_count = doc.page_count
    doc.close()

    normalized = re.sub(r"\s+", " ", full_text).strip()
    is_meaningful = len(normalized) >= min_length_for_digital and _meaningful_char_ratio(normalized) > 0.4

    return ExtractedText(text=full_text, page_count=page_count, is_meaningful=is_meaningful)


def render_first_page_to_image(pdf_bytes: bytes, *, zoom: float = 2.0) -> Image.Image:
    """Render page 1 to a PIL image for OCR / vision-model consumption."""
    try:
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    except Exception as exc:
        raise InvalidPDFError(f"Could not open file as a PDF: {exc}") from exc

    if doc.page_count == 0:
        doc.close()
        raise InvalidPDFError("PDF has no pages.")

    page = doc[0]
    matrix = fitz.Matrix(zoom, zoom)
    pix = page.get_pixmap(matrix=matrix)
    img_bytes = pix.tobytes("png")
    doc.close()
    return Image.open(BytesIO(img_bytes)).convert("RGB")

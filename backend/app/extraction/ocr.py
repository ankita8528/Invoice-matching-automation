"""Tesseract OCR wrapper for scanned/image PDFs.

Failure to run Tesseract (binary not installed/configured) is a recoverable
condition: the caller should surface a REVIEW decision rather than crash the
request. See processing_service for how OCRUnavailableError is handled.
"""
from __future__ import annotations

import pytesseract
from PIL import Image


class OCRUnavailableError(Exception):
    pass


def configure_tesseract(tesseract_cmd: str) -> None:
    if tesseract_cmd:
        pytesseract.pytesseract.tesseract_cmd = tesseract_cmd


def run_ocr(image: Image.Image) -> str:
    try:
        return pytesseract.image_to_string(image)
    except pytesseract.TesseractNotFoundError as exc:
        raise OCRUnavailableError(
            "Tesseract OCR binary was not found. Set TESSERACT_CMD in .env or install Tesseract "
            "and ensure it's on PATH."
        ) from exc
    except Exception as exc:
        raise OCRUnavailableError(f"Tesseract OCR failed: {exc}") from exc

"""Qwen3-VL (via Ollama) structured extraction for scanned/image invoices.

The vision model is ONLY used for document understanding: turning pixels +
OCR text into a structured JSON guess at the invoice fields. It never
performs arithmetic and it is never the final decision-maker -- its output
is normalized into the same StructuredInvoice schema as the digital-text
path and then runs through the exact same deterministic validation/matching/
decision pipeline.

The provider is configurable (`VISION_PROVIDER`); only "ollama" is
implemented, matching the "prefer local inference through Ollama" ask. No
API keys are hard-coded -- everything comes from config.py / environment.
"""
from __future__ import annotations

import base64
import json
import re
from io import BytesIO

import requests
from PIL import Image

PROMPT = """You are an invoice data extraction engine. You will be given an invoice \
image and OCR text extracted from it. Extract the invoice fields and return ONLY a \
single JSON object -- no prose, no markdown code fences, no explanation -- matching \
EXACTLY this shape:

{
  "invoice_details": {
    "vendor_name": null,
    "invoice_number": null,
    "invoice_date": null,
    "po_number": null
  },
  "line_items": [
    {"item_name": null, "description": null, "quantity": null, "unit_price": null, "amount": null}
  ],
  "payment_details": {
    "subtotal_amount": null,
    "tax_amount": null,
    "total_amount": null
  }
}

Rules:
- If a field cannot be reliably read, set it to null. NEVER invent or guess a value.
- Numbers must be plain JSON numbers (no currency symbols, no thousands separators).
- invoice_date should be in YYYY-MM-DD format if determinable, otherwise the raw text you see, otherwise null.
- Return valid JSON and nothing else.

OCR text extracted from the same document (may contain errors -- cross-check against the image):
---
{ocr_text}
---
"""


class VisionExtractionError(Exception):
    pass


def _image_to_base64(image: Image.Image) -> str:
    buf = BytesIO()
    image.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode("utf-8")


def _strip_code_fences(text: str) -> str:
    text = text.strip()
    match = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    if match:
        return match.group(1).strip()
    return text


def _extract_first_json_object(text: str) -> dict:
    text = _strip_code_fences(text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    # Fall back to locating the first {...} balanced object in the text.
    start = text.find("{")
    if start == -1:
        raise VisionExtractionError(f"Vision model did not return JSON. Raw output: {text[:300]!r}")
    depth = 0
    for i in range(start, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                candidate = text[start : i + 1]
                try:
                    return json.loads(candidate)
                except json.JSONDecodeError as exc:
                    raise VisionExtractionError(f"Malformed JSON from vision model: {exc}. Raw: {candidate[:300]!r}") from exc
    raise VisionExtractionError(f"Vision model returned unterminated JSON. Raw output: {text[:300]!r}")


def extract_via_ollama(
    image: Image.Image,
    ocr_text: str,
    *,
    model: str,
    base_url: str,
    timeout_seconds: int,
) -> dict:
    prompt = PROMPT.replace("{ocr_text}", ocr_text or "(no OCR text available)")
    payload = {
        "model": model,
        "prompt": prompt,
        "images": [_image_to_base64(image)],
        "format": "json",
        "stream": False,
        "options": {"temperature": 0},
    }
    try:
        resp = requests.post(f"{base_url.rstrip('/')}/api/generate", json=payload, timeout=timeout_seconds)
        resp.raise_for_status()
    except requests.exceptions.ConnectionError as exc:
        raise VisionExtractionError(
            f"Could not reach Ollama at {base_url}. Is Ollama running and is '{model}' pulled? ({exc})"
        ) from exc
    except requests.exceptions.Timeout as exc:
        raise VisionExtractionError(f"Ollama request timed out after {timeout_seconds}s.") from exc
    except requests.exceptions.HTTPError as exc:
        raise VisionExtractionError(f"Ollama returned an error: {exc}") from exc

    data = resp.json()
    raw_output = data.get("response", "")
    return _extract_first_json_object(raw_output)


def extract_structured_json(
    image: Image.Image,
    ocr_text: str,
    *,
    provider: str,
    model: str,
    base_url: str,
    timeout_seconds: int,
) -> dict:
    if provider == "ollama":
        return extract_via_ollama(image, ocr_text, model=model, base_url=base_url, timeout_seconds=timeout_seconds)
    raise VisionExtractionError(f"Unsupported VISION_PROVIDER '{provider}'. Only 'ollama' is implemented.")

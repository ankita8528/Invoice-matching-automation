"""Qwen3-VL structured extraction for scanned/image invoices.

The vision model is ONLY used for document understanding: turning pixels +
OCR text into a structured JSON guess at the invoice fields. It never
performs arithmetic and it is never the final decision-maker -- its output
is normalized into the same StructuredInvoice schema as the digital-text
path and then runs through the exact same deterministic validation/matching/
decision pipeline.

The provider is configurable (`VISION_PROVIDER`):
  - "ollama"       -- local inference via an Ollama server (preferred; no
                       network dependency, no per-request cost).
  - "huggingface"  -- Hugging Face Inference Providers (OpenAI-compatible
                       chat-completions), useful when local hardware can't
                       run an 8B vision model at a reasonable speed/memory
                       footprint (CPU-only inference has been observed to
                       take several minutes and nearly exhaust RAM on a
                       16GB laptop -- see README section 6).
No API keys are hard-coded anywhere -- the HF token comes from
HF_API_TOKEN in the environment (see .env.example) and is never logged.
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


def _safe_response_json(resp: requests.Response, provider_name: str) -> dict:
    """resp.json() but never lets a malformed HTTP response body (e.g. extra
    trailing data some gateways occasionally emit) become an uncaught
    exception -- that must degrade to REVIEW like every other extraction
    failure, never bubble up as an unhandled 500.
    """
    try:
        return resp.json()
    except ValueError as exc:  # json.JSONDecodeError is a ValueError subclass
        raise VisionExtractionError(f"{provider_name} returned a response that wasn't valid JSON: {exc}. Raw: {resp.text[:300]!r}") from exc


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
        # Deliberately NOT using Ollama's format="json" grammar-constrained
        # decoding here: with some vision-model/Ollama version combinations it
        # has been observed to return an empty `response` for multimodal
        # prompts. The prompt itself already demands JSON-only output, and
        # _extract_first_json_object() below defensively strips code fences /
        # finds the first balanced {...} object, so plain free-form decoding
        # plus that repair step is more reliable in practice.
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

    data = _safe_response_json(resp, "Ollama")
    raw_output = data.get("response", "")
    return _extract_first_json_object(raw_output)


def extract_via_huggingface(
    image: Image.Image,
    ocr_text: str,
    *,
    model: str,
    api_token: str,
    base_url: str,
    timeout_seconds: int,
) -> dict:
    """Hugging Face Inference Providers, OpenAI-compatible chat-completions API.

    See https://huggingface.co/docs/inference-providers/en/tasks/chat-completion .
    `model` is a Hub model id, optionally with a `:provider` suffix (e.g.
    "Qwen/Qwen3-VL-8B-Instruct:featherless-ai") to pin a specific provider;
    without a suffix, HF routes to whichever provider currently serves it.
    """
    if not api_token:
        raise VisionExtractionError(
            "HF_API_TOKEN is not set. Create a token with 'Inference Providers' permission at "
            "https://huggingface.co/settings/tokens and set HF_API_TOKEN in .env."
        )

    prompt = PROMPT.replace("{ocr_text}", ocr_text or "(no OCR text available)")
    image_data_uri = f"data:image/png;base64,{_image_to_base64(image)}"
    payload = {
        "model": model,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": image_data_uri}},
                ],
            }
        ],
        "temperature": 0,
    }
    headers = {"Authorization": f"Bearer {api_token}"}
    try:
        resp = requests.post(
            f"{base_url.rstrip('/')}/chat/completions", json=payload, headers=headers, timeout=timeout_seconds
        )
        resp.raise_for_status()
    except requests.exceptions.ConnectionError as exc:
        raise VisionExtractionError(f"Could not reach Hugging Face Inference Providers at {base_url}. ({exc})") from exc
    except requests.exceptions.Timeout as exc:
        raise VisionExtractionError(f"Hugging Face request timed out after {timeout_seconds}s.") from exc
    except requests.exceptions.HTTPError as exc:
        detail = ""
        try:
            detail = resp.text[:300]
        except Exception:  # noqa: BLE001
            pass
        raise VisionExtractionError(f"Hugging Face returned an error: {exc}. {detail}") from exc

    data = _safe_response_json(resp, "Hugging Face")
    try:
        raw_output = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise VisionExtractionError(f"Unexpected Hugging Face response shape: {data!r}") from exc
    return _extract_first_json_object(raw_output or "")


def extract_structured_json(
    image: Image.Image,
    ocr_text: str,
    *,
    provider: str,
    model: str,
    base_url: str,
    timeout_seconds: int,
    hf_api_token: str = "",
) -> dict:
    if provider == "ollama":
        return extract_via_ollama(image, ocr_text, model=model, base_url=base_url, timeout_seconds=timeout_seconds)
    if provider == "huggingface":
        return extract_via_huggingface(
            image, ocr_text, model=model, api_token=hf_api_token, base_url=base_url, timeout_seconds=timeout_seconds
        )
    raise VisionExtractionError(f"Unsupported VISION_PROVIDER '{provider}'. Use 'ollama' or 'huggingface'.")

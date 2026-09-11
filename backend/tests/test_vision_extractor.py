import requests
import pytest
from PIL import Image

from app.extraction.vision_extractor import (
    VisionExtractionError,
    _extract_first_json_object,
    _safe_response_json,
    extract_structured_json,
    extract_via_huggingface,
)


def _fake_response(body: str, status_code: int = 200) -> requests.Response:
    resp = requests.Response()
    resp.status_code = status_code
    resp._content = body.encode("utf-8")
    return resp


def test_extract_first_json_object_plain():
    assert _extract_first_json_object('{"a": 1}') == {"a": 1}


def test_extract_first_json_object_strips_code_fences():
    text = '```json\n{"a": 1, "b": [1, 2]}\n```'
    assert _extract_first_json_object(text) == {"a": 1, "b": [1, 2]}


def test_extract_first_json_object_finds_balanced_object_amid_prose():
    text = 'Sure, here is the JSON: {"a": 1, "nested": {"b": 2}} -- hope that helps!'
    assert _extract_first_json_object(text) == {"a": 1, "nested": {"b": 2}}


def test_extract_first_json_object_raises_on_empty_string():
    with pytest.raises(VisionExtractionError):
        _extract_first_json_object("")


def test_huggingface_missing_token_raises_clear_error():
    image = Image.new("RGB", (10, 10))
    with pytest.raises(VisionExtractionError, match="HF_API_TOKEN"):
        extract_via_huggingface(
            image, "", model="Qwen/Qwen3-VL-8B-Instruct", api_token="", base_url="https://router.huggingface.co/v1", timeout_seconds=5
        )


def test_safe_response_json_valid_body():
    resp = _fake_response('{"choices": [{"message": {"content": "{}"}}]}')
    assert _safe_response_json(resp, "Hugging Face")["choices"][0]["message"]["content"] == "{}"


def test_safe_response_json_malformed_body_degrades_gracefully():
    """Regression test: a gateway/provider returning trailing extra data after
    the JSON body (json.JSONDecodeError: 'Extra data') must become a
    VisionExtractionError (-> REVIEW upstream), never an uncaught exception
    that would surface as a raw 500.
    """
    resp = _fake_response('{"choices": []}{"unexpected": "trailing object"}')
    with pytest.raises(VisionExtractionError, match="wasn't valid JSON"):
        _safe_response_json(resp, "Hugging Face")


def test_extract_structured_json_rejects_unsupported_provider():
    image = Image.new("RGB", (10, 10))
    with pytest.raises(VisionExtractionError, match="Unsupported VISION_PROVIDER"):
        extract_structured_json(image, "", provider="bedrock", model="x", base_url="http://x", timeout_seconds=5)

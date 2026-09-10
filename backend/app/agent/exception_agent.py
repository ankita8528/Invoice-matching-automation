"""Optional, explicitly-gated agentic exception-handling layer.

This is NOT an autonomous agent that runs the pipeline -- the deterministic
pipeline in services/processing_service.py always runs first and always
produces the authoritative decision. When ENABLE_EXCEPTION_AGENT=true and the
decision is REVIEW (an uncertain case: missing/ambiguous PO, possible
duplicate, possible split invoice, unclear scanned invoice, etc.), this
module makes ONE additional read-only LLM call to produce a human-readable
investigation summary and a suggested next action for an AP analyst.

Hard constraints:
- It never changes `decision` or any CheckResult.
- If it's disabled, errors out, or the model is unreachable, the pipeline
  continues normally with `ai_exception_analysis = None` (or an error note).
"""
from __future__ import annotations

import json
import logging

import requests

logger = logging.getLogger("app.agent")


def build_context_summary(*, checks: dict, po_candidates: list, duplicate, split_info, vendor) -> str:
    lines = [
        "Checks:",
        *[f"  - {name}: {result.status} ({result.reason})" for name, result in checks.items()],
        f"Duplicate status: {duplicate.status} ({duplicate.reason})",
        f"Vendor status: {vendor.status} (confidence {vendor.match_confidence:.2f})",
        f"Split invoice: {split_info.invoice_type}",
    ]
    if po_candidates:
        lines.append("PO candidates:")
        for c in po_candidates:
            lines.append(f"  - {c.po_number}: score={c.score:.2f} reasons={c.reasons}")
    return "\n".join(lines)


PROMPT_TEMPLATE = """You are an accounts-payable exception assistant. An invoice was routed to \
REVIEW by a deterministic rules engine. You do NOT make the final decision and you must NOT \
claim the invoice is approved or rejected -- only explain the exception and suggest what a \
human AP analyst should check next. Be concise (3-5 sentences). Return ONLY a JSON object of \
the shape {{"analysis": "...", "suggested_next_action": "..."}}.

Context:
{context}
"""


def investigate(
    *,
    context_summary: str,
    model: str,
    base_url: str,
    timeout_seconds: int,
) -> dict | None:
    prompt = PROMPT_TEMPLATE.format(context=context_summary)
    try:
        resp = requests.post(
            f"{base_url.rstrip('/')}/api/generate",
            json={"model": model, "prompt": prompt, "format": "json", "stream": False, "options": {"temperature": 0.2}},
            timeout=timeout_seconds,
        )
        resp.raise_for_status()
        raw = resp.json().get("response", "")
        return json.loads(raw)
    except Exception as exc:  # noqa: BLE001 - this layer must never crash the request
        logger.warning("Exception agent unavailable/failed: %s", exc)
        return {"analysis": None, "suggested_next_action": None, "error": str(exc)}

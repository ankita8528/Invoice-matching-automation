"""Deterministic normalization helpers used everywhere identity comparisons
happen: PO numbers, invoice numbers, vendor names.

These are pure functions with no I/O so they're trivial to unit test.
"""
from __future__ import annotations

import re

# Common legal-entity suffixes that should not affect vendor identity matching.
_VENDOR_SUFFIX_MAP = {
    "PRIVATELIMITED": "PVTLTD",
    "PVTLTD": "PVTLTD",
    "PVTLIMITED": "PVTLTD",
    "PRIVATELTD": "PVTLTD",
    "LIMITED": "LTD",
    "LLC": "LLC",
    "INCORPORATED": "INC",
    "CORPORATION": "CORP",
}

_ALNUM_RE = re.compile(r"[^A-Za-z0-9]")
_WHITESPACE_RE = re.compile(r"\s+")


def normalize_po_number(raw: str | None) -> str:
    """Strip spaces/hyphens/slashes/punctuation and uppercase.

    'PO-1005', 'PO 1005', 'po/1005', 'PO1005' all normalize to 'PO1005'.
    Returns '' for None/empty input (never None, so callers can compare safely).
    """
    if not raw:
        return ""
    return _ALNUM_RE.sub("", raw).upper()


def normalize_invoice_number(raw: str | None) -> str:
    """Same normalization strategy as PO numbers: identity comparison, not display."""
    if not raw:
        return ""
    return _ALNUM_RE.sub("", raw).upper()


def normalize_vendor_name(raw: str | None) -> str:
    """Normalize a vendor name for identity comparison.

    Handles case, punctuation, extra whitespace, and common legal-entity
    suffix variations (Pvt Ltd / Private Limited / Ltd / Limited / etc.)
    by folding them to a canonical token.
    """
    if not raw:
        return ""
    text = raw.upper()
    text = re.sub(r"[.,]", "", text)
    text = _WHITESPACE_RE.sub(" ", text).strip()
    # Fold multi-word legal suffixes down to single tokens before stripping
    # remaining punctuation, so "Pvt. Ltd." and "Private Limited" collapse
    # to the same canonical suffix.
    text = text.replace("PRIVATE LIMITED", "PRIVATELIMITED")
    text = text.replace("PVT LTD", "PVTLTD")
    text = text.replace("PVT LIMITED", "PVTLIMITED")
    text = text.replace("PRIVATE LTD", "PRIVATELTD")
    tokens = text.split(" ")
    folded = [_VENDOR_SUFFIX_MAP.get(tok, tok) for tok in tokens]
    collapsed = " ".join(folded)
    # Final pass: remove all remaining non-alphanumeric characters and spaces
    # so "Apex Office Supplies Pvt Ltd" and "Apex Office Supplies, PVTLTD" match.
    return _ALNUM_RE.sub("", collapsed)


def normalize_text(raw: str | None) -> str:
    if not raw:
        return ""
    return _WHITESPACE_RE.sub(" ", raw.strip().lower())

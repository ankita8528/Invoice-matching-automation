"""Fuzzy / semantic similarity helpers used only for *scoring candidates*,
never for making a final financial decision on their own (see po_matcher.py
and rules/decision_engine.py for where confidence thresholds are enforced).
"""
from __future__ import annotations

from rapidfuzz import fuzz

from app.matching.normalization import normalize_text, normalize_vendor_name


def vendor_similarity(a: str | None, b: str | None) -> float:
    """Return a 0-1 similarity score between two vendor names.

    Exact match after normalization -> 1.0. Otherwise falls back to a
    token-sort fuzzy ratio on the normalized strings, so this always
    comes with a recorded confidence rather than a blind boolean.
    """
    na, nb = normalize_vendor_name(a), normalize_vendor_name(b)
    if not na or not nb:
        return 0.0
    if na == nb:
        return 1.0
    return fuzz.token_sort_ratio(na, nb) / 100.0


def text_similarity(a: str | None, b: str | None) -> float:
    """Generic 0-1 fuzzy similarity for free-text fields (item names/descriptions)."""
    na, nb = normalize_text(a), normalize_text(b)
    if not na or not nb:
        return 0.0
    return fuzz.token_set_ratio(na, nb) / 100.0


def numeric_closeness(a: float | None, b: float | None, rel_tolerance: float = 0.02) -> float:
    """Return a 0-1 score for how close two numbers are (1.0 = identical,
    0.0 = differ by >= 50%). Used only as a *matching signal*, not a
    tolerance/business-rule check.
    """
    if a is None or b is None:
        return 0.0
    if a == 0 and b == 0:
        return 1.0
    denom = max(abs(a), abs(b), 1e-9)
    diff_ratio = abs(a - b) / denom
    if diff_ratio <= rel_tolerance:
        return 1.0
    score = 1.0 - min(diff_ratio, 1.0)
    return max(0.0, score)

"""Vendor-specific tolerance math. Pure Python, no LLM involvement -- an
amount is either within tolerance or it isn't, and that's a fact, not a
judgment call for a language model.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ToleranceResult:
    allowed_difference: float
    difference: float
    within_tolerance: bool
    tolerance_type: str
    tolerance_value: float


def compute_allowed_tolerance(reference_amount: float, tolerance_type: str, tolerance_value: float) -> float:
    if tolerance_type == "percentage":
        return round(reference_amount * (tolerance_value / 100.0), 2)
    if tolerance_type == "absolute":
        return round(tolerance_value, 2)
    return 0.0


def check_tolerance(invoice_amount: float, reference_amount: float, tolerance_type: str, tolerance_value: float) -> ToleranceResult:
    allowed = compute_allowed_tolerance(reference_amount, tolerance_type, tolerance_value)
    diff = round(invoice_amount - reference_amount, 2)
    return ToleranceResult(
        allowed_difference=allowed,
        difference=diff,
        within_tolerance=abs(diff) <= allowed,
        tolerance_type=tolerance_type,
        tolerance_value=tolerance_value,
    )

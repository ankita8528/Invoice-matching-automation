"""Vendor identity + approval-status validation against the vendor master."""
from __future__ import annotations

from dataclasses import dataclass

from app.matching.fuzzy_matcher import vendor_similarity
from app.matching.normalization import normalize_vendor_name
from app.models.result import CheckResult, CheckStatus, VendorInfo

# Vendor identity matches at or above this fuzzy score are accepted, but the
# confidence is always recorded rather than silently trusted.
FUZZY_VENDOR_MATCH_FLOOR = 0.90


@dataclass
class VendorRecord:
    vendor_id: str
    vendor_name: str
    vendor_name_normalized: str
    status: str
    tolerance_type: str
    tolerance_value: float


def find_vendor(vendor_name: str | None, vendors: list[VendorRecord]) -> tuple[VendorRecord | None, float, str]:
    """Returns (vendor_record_or_None, confidence, match_method)."""
    if not vendor_name:
        return None, 0.0, "no_vendor_name"

    normalized = normalize_vendor_name(vendor_name)
    for v in vendors:
        if v.vendor_name_normalized == normalized:
            return v, 1.0, "exact_normalized"

    best_vendor, best_score = None, 0.0
    for v in vendors:
        score = vendor_similarity(vendor_name, v.vendor_name)
        if score > best_score:
            best_vendor, best_score = v, score

    if best_vendor and best_score >= FUZZY_VENDOR_MATCH_FLOOR:
        return best_vendor, best_score, "fuzzy"

    return None, best_score, "no_match"


def validate_vendor(vendor_name: str | None, vendors: list[VendorRecord]) -> tuple[CheckResult, VendorInfo]:
    record, confidence, method = find_vendor(vendor_name, vendors)

    if record is None:
        info = VendorInfo(status="UNKNOWN", match_confidence=confidence)
        return (
            CheckResult(
                status=CheckStatus.FAIL,
                reason=f"Vendor '{vendor_name}' could not be matched to the vendor master (best fuzzy score {confidence:.2f}).",
            ),
            info,
        )

    info = VendorInfo(
        vendor_id=record.vendor_id,
        matched_name=record.vendor_name,
        status=record.status,
        match_confidence=confidence,
        tolerance_type=record.tolerance_type,
        tolerance_value=record.tolerance_value,
    )

    if record.status != "APPROVED":
        return (
            CheckResult(
                status=CheckStatus.FAIL,
                expected="APPROVED",
                actual=record.status,
                reason=f"Vendor '{record.vendor_name}' has status {record.status} (matched via {method}, confidence {confidence:.2f}).",
            ),
            info,
        )

    status = CheckStatus.PASS if method == "exact_normalized" else CheckStatus.WARNING
    reason = f"Vendor '{record.vendor_name}' is APPROVED (matched via {method}, confidence {confidence:.2f})."
    return CheckResult(status=status, reason=reason), info

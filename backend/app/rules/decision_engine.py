"""The deterministic decision engine.

This is the ONLY place a final APPROVE / APPROVE_PARTIAL / REVIEW / REJECT
decision is produced. It consumes already-computed CheckResults and domain
objects (never raw AI output) and applies a fixed precedence: REJECT
conditions first, then REVIEW conditions, then APPROVE/APPROVE_PARTIAL.

No business rule lives in the API layer -- routes.py only calls
processing_service, which calls this module.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from app.matching.po_matcher import MatchResult
from app.models.result import CheckResult, CheckStatus, Decision, DuplicateInfo, SplitInvoiceInfo, VendorInfo


@dataclass
class DecisionOutcome:
    decision: Decision
    reason: str
    triggered_rules: list[str] = field(default_factory=list)


def decide(
    *,
    checks: dict[str, CheckResult],
    duplicate: DuplicateInfo,
    vendor: VendorInfo,
    match_result: MatchResult,
    split_info: SplitInvoiceInfo,
) -> DecisionOutcome:
    reject_reasons: list[str] = []
    review_reasons: list[str] = []

    # ---------------- REJECT conditions (checked first, hard failures) ----------------
    if duplicate.status in ("EXACT_DUPLICATE", "VENDOR_INVOICE_DUPLICATE"):
        reject_reasons.append(duplicate.reason)

    if vendor.status == "NOT_APPROVED":
        reject_reasons.append(checks["vendor_approved"].reason)

    if checks.get("vendor_po_identity_conflict", CheckResult(status=CheckStatus.PASS)).status == CheckStatus.FAIL:
        reject_reasons.append(checks["vendor_po_identity_conflict"].reason)

    if reject_reasons:
        return DecisionOutcome(decision=Decision.REJECT, reason=reject_reasons[0], triggered_rules=reject_reasons)

    # ---------------- REVIEW conditions ----------------
    if checks["required_fields_present"].status in (CheckStatus.FAIL, CheckStatus.WARNING):
        review_reasons.append(checks["required_fields_present"].reason)

    if checks["invoice_extraction"].status in (CheckStatus.FAIL, CheckStatus.WARNING):
        review_reasons.append(checks["invoice_extraction"].reason)

    if vendor.status == "UNKNOWN":
        review_reasons.append(checks["vendor_approved"].reason)

    if match_result.match_method in ("ambiguous", "no_match"):
        review_reasons.append(match_result.reason)

    if match_result.match_method == "semantic_candidate_match":
        # The PO number was missing/unusable on the invoice and was only
        # resolved via vendor/item/amount candidate scoring. Per R002-style
        # policy, a missing PO reference is never auto-approved solely on
        # candidate confidence -- it always needs a human to confirm the
        # inferred PO, no matter how strong the match score is.
        review_reasons.append(
            f"PO number was missing on the invoice; matched to {match_result.matched_po.po_number} via "
            f"candidate scoring (confidence {match_result.match_confidence:.2f}), which requires human "
            f"confirmation rather than automatic approval."
        )

    if checks["arithmetic_check"].status == CheckStatus.FAIL:
        review_reasons.append(checks["arithmetic_check"].reason)

    if checks.get("quantity_match", CheckResult(status=CheckStatus.PASS)).status == CheckStatus.FAIL:
        review_reasons.append(checks["quantity_match"].reason)

    if checks.get("unit_price_match", CheckResult(status=CheckStatus.PASS)).status == CheckStatus.FAIL:
        review_reasons.append(checks["unit_price_match"].reason)

    if checks.get("line_item_match", CheckResult(status=CheckStatus.PASS)).status == CheckStatus.FAIL:
        review_reasons.append(checks["line_item_match"].reason)

    if checks.get("tolerance_check", CheckResult(status=CheckStatus.PASS)).status == CheckStatus.FAIL:
        review_reasons.append(checks["tolerance_check"].reason)

    if duplicate.status == "POTENTIAL_DUPLICATE":
        review_reasons.append(duplicate.reason)

    if review_reasons:
        return DecisionOutcome(decision=Decision.REVIEW, reason=review_reasons[0], triggered_rules=review_reasons)

    # ---------------- APPROVE / APPROVE_PARTIAL ----------------
    if split_info.invoice_type == "PARTIAL_INVOICE":
        reason = (
            f"Valid partial/split invoice against PO: cumulative invoiced "
            f"{split_info.cumulative_invoiced} of PO amount {split_info.po_amount} "
            f"(remaining balance {split_info.remaining_balance}). All other checks passed."
        )
        return DecisionOutcome(decision=Decision.APPROVE_PARTIAL, reason=reason)

    return DecisionOutcome(decision=Decision.APPROVE, reason="All required checks passed and the invoice matches its purchase order within tolerance.")

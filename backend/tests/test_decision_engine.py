from app.matching.po_matcher import MatchResult
from app.models.po import PurchaseOrder
from app.models.result import CheckResult, CheckStatus, DuplicateInfo, SplitInvoiceInfo, VendorInfo
from app.rules.decision_engine import decide

PASS = CheckResult(status=CheckStatus.PASS)


def _base_checks(**overrides):
    checks = {
        "invoice_extraction": PASS,
        "required_fields_present": PASS,
        "arithmetic_check": PASS,
        "duplicate_check": PASS,
        "vendor_approved": PASS,
        "po_number_match": PASS,
        "po_match": PASS,
        "line_item_match": PASS,
        "quantity_match": PASS,
        "unit_price_match": PASS,
        "tolerance_check": PASS,
        "split_invoice_check": PASS,
        "vendor_po_identity_conflict": PASS,
    }
    checks.update(overrides)
    return checks


def _po():
    return PurchaseOrder(po_number="PO1001", po_number_normalized="PO1001", vendor_name="Apex", vendor_name_normalized="apex", po_amount=25000)


def test_approve_when_all_checks_pass():
    outcome = decide(
        checks=_base_checks(),
        duplicate=DuplicateInfo(status="NONE"),
        vendor=VendorInfo(status="APPROVED"),
        match_result=MatchResult(matched_po=_po(), match_method="exact_normalized_po", match_confidence=1.0),
        split_info=SplitInvoiceInfo(invoice_type="FULL_INVOICE"),
    )
    assert outcome.decision == "APPROVE"


def test_reject_on_exact_duplicate():
    outcome = decide(
        checks=_base_checks(),
        duplicate=DuplicateInfo(status="EXACT_DUPLICATE", reason="dup"),
        vendor=VendorInfo(status="APPROVED"),
        match_result=MatchResult(matched_po=_po(), match_method="exact_normalized_po", match_confidence=1.0),
        split_info=SplitInvoiceInfo(invoice_type="FULL_INVOICE"),
    )
    assert outcome.decision == "REJECT"


def test_reject_on_unapproved_vendor():
    outcome = decide(
        checks=_base_checks(vendor_approved=CheckResult(status=CheckStatus.FAIL, reason="not approved")),
        duplicate=DuplicateInfo(status="NONE"),
        vendor=VendorInfo(status="NOT_APPROVED"),
        match_result=MatchResult(matched_po=_po(), match_method="exact_normalized_po", match_confidence=1.0),
        split_info=SplitInvoiceInfo(invoice_type="FULL_INVOICE"),
    )
    assert outcome.decision == "REJECT"


def test_review_on_ambiguous_po_match():
    outcome = decide(
        checks=_base_checks(),
        duplicate=DuplicateInfo(status="NONE"),
        vendor=VendorInfo(status="APPROVED"),
        match_result=MatchResult(matched_po=None, match_method="ambiguous", match_confidence=0.8, reason="ambiguous"),
        split_info=SplitInvoiceInfo(invoice_type="FULL_INVOICE"),
    )
    assert outcome.decision == "REVIEW"


def test_review_when_po_was_missing_even_if_candidate_match_is_confident():
    """A missing PO number resolved only via level-3 candidate scoring must
    never be silently auto-approved, no matter how confident the match --
    it always needs a human to confirm the inferred PO.
    """
    outcome = decide(
        checks=_base_checks(),
        duplicate=DuplicateInfo(status="NONE"),
        vendor=VendorInfo(status="APPROVED"),
        match_result=MatchResult(matched_po=_po(), match_method="semantic_candidate_match", match_confidence=1.0, reason="confident candidate match"),
        split_info=SplitInvoiceInfo(invoice_type="FULL_INVOICE"),
    )
    assert outcome.decision == "REVIEW"


def test_review_on_tolerance_failure():
    outcome = decide(
        checks=_base_checks(tolerance_check=CheckResult(status=CheckStatus.FAIL, reason="over tolerance")),
        duplicate=DuplicateInfo(status="NONE"),
        vendor=VendorInfo(status="APPROVED"),
        match_result=MatchResult(matched_po=_po(), match_method="exact_normalized_po", match_confidence=1.0),
        split_info=SplitInvoiceInfo(invoice_type="FULL_INVOICE"),
    )
    assert outcome.decision == "REVIEW"


def test_approve_partial_for_split_invoice():
    outcome = decide(
        checks=_base_checks(),
        duplicate=DuplicateInfo(status="NONE"),
        vendor=VendorInfo(status="APPROVED"),
        match_result=MatchResult(matched_po=_po(), match_method="exact_normalized_po", match_confidence=1.0),
        split_info=SplitInvoiceInfo(invoice_type="PARTIAL_INVOICE", po_amount=100000, previously_invoiced=40000, current_invoice=30000, cumulative_invoiced=70000, remaining_balance=30000),
    )
    assert outcome.decision == "APPROVE_PARTIAL"

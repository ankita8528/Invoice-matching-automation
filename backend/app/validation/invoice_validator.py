"""Required-field validation for the extracted invoice.

Missing PO number is explicitly NOT a hard failure here (PO matching level 3
exists precisely to handle that). Missing invoice number/date/total are
treated as WARNING-level issues that the decision engine turns into REVIEW,
never an automatic REJECT.
"""
from __future__ import annotations

from app.models.invoice import StructuredInvoice
from app.models.result import CheckResult, CheckStatus


def validate_required_fields(invoice: StructuredInvoice) -> CheckResult:
    d = invoice.invoice_details
    p = invoice.payment_details

    missing_soft: list[str] = []
    if not d.invoice_number:
        missing_soft.append("invoice_number")
    if not d.invoice_date:
        missing_soft.append("invoice_date")
    if not d.vendor_name:
        missing_soft.append("vendor_name")
    if p.total_amount is None:
        missing_soft.append("total_amount")
    if not invoice.line_items:
        missing_soft.append("line_items")

    missing_po = not d.po_number

    if missing_soft:
        reason = "Missing fields: " + ", ".join(missing_soft)
        if missing_po:
            reason += " (PO number is also missing but is not, by itself, a failure)"
        return CheckResult(status=CheckStatus.WARNING, reason=reason, expected="all required fields present", actual=f"missing: {missing_soft}")

    if missing_po:
        # Deliberately PASS: a missing PO number must not, by itself, force
        # a REVIEW here -- level-3 candidate matching (po_matcher.py) is what
        # decides whether this is resolvable, and the decision engine reacts
        # to *that* outcome (ambiguous/no_match -> REVIEW), not to this check.
        return CheckResult(
            status=CheckStatus.PASS,
            reason="All other required invoice fields are present. PO number is missing; "
            "will attempt candidate matching on vendor/line items instead.",
        )

    return CheckResult(status=CheckStatus.PASS, reason="All required invoice fields are present.")

"""Deterministic arithmetic validation. An LLM never performs these
calculations -- everything here is plain Python arithmetic.
"""
from __future__ import annotations

from app.models.invoice import StructuredInvoice
from app.models.result import CheckResult, CheckStatus


def validate_arithmetic(invoice: StructuredInvoice, *, epsilon: float) -> CheckResult:
    """Check that (a) each line item's amount == quantity * unit_price, and
    (b) subtotal + tax == total, within a small rounding epsilon.
    """
    line_item_issues: list[str] = []
    for idx, item in enumerate(invoice.line_items, start=1):
        if item.quantity is not None and item.unit_price is not None and item.amount is not None:
            expected = round(item.quantity * item.unit_price, 2)
            if abs(expected - item.amount) > epsilon:
                line_item_issues.append(
                    f"line {idx}: quantity({item.quantity}) x unit_price({item.unit_price}) "
                    f"= {expected}, but stated amount is {item.amount}"
                )

    subtotal = invoice.payment_details.subtotal_amount
    tax = invoice.payment_details.tax_amount
    total = invoice.payment_details.total_amount

    if subtotal is None and invoice.line_items:
        computed_amounts = [i.amount for i in invoice.line_items if i.amount is not None]
        subtotal = round(sum(computed_amounts), 2) if computed_amounts else None

    expected_total = None
    if subtotal is not None and tax is not None:
        expected_total = round(subtotal + tax, 2)
    elif subtotal is not None and tax is None:
        expected_total = round(subtotal, 2)

    total_mismatch = None
    if expected_total is not None and total is not None:
        diff = round(total - expected_total, 2)
        if abs(diff) > epsilon:
            total_mismatch = diff

    if line_item_issues or total_mismatch is not None:
        reasons = list(line_item_issues)
        if total_mismatch is not None:
            reasons.append(f"subtotal({subtotal}) + tax({tax}) = {expected_total}, but stated total is {total}")
        return CheckResult(
            status=CheckStatus.FAIL,
            expected=expected_total,
            actual=total,
            difference=total_mismatch,
            reason="; ".join(reasons),
        )

    if expected_total is None or total is None:
        return CheckResult(
            status=CheckStatus.WARNING,
            expected=expected_total,
            actual=total,
            reason="Insufficient data to fully validate invoice arithmetic (missing subtotal/tax/total).",
        )

    return CheckResult(
        status=CheckStatus.PASS,
        expected=expected_total,
        actual=total,
        difference=0,
        reason="Line-item amounts and subtotal+tax reconcile with the stated total.",
    )

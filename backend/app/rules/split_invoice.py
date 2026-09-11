"""Split/partial invoice handling.

A vendor may invoice a single PO across several invoices. This module
computes cumulative-invoiced-vs-PO-amount purely from the persistent
po_invoice_cache (see rules/po_invoice_cache.py) so the numbers are correct
across restarts.
"""
from __future__ import annotations

from app.models.result import SplitInvoiceInfo
from app.rules.po_invoice_cache import POInvoiceCache
from app.rules.tolerance import check_tolerance


def evaluate_split_invoice(
    *,
    po_number_normalized: str | None,
    current_invoice_total: float | None,
    po_amount: float,
    tolerance_type: str,
    tolerance_value: float,
    cache: POInvoiceCache,
) -> SplitInvoiceInfo:
    if not po_number_normalized or current_invoice_total is None:
        return SplitInvoiceInfo(invoice_type="FULL_INVOICE")

    prior_amounts = cache.get_prior_amounts(po_number_normalized)
    previously_invoiced = round(sum(prior_amounts), 2)
    cumulative = round(previously_invoiced + current_invoice_total, 2)
    remaining = round(po_amount - cumulative, 2)

    tol = check_tolerance(cumulative, po_amount, tolerance_type, tolerance_value)

    is_partial_sequence = previously_invoiced > 0 or (remaining > tol.allowed_difference)
    invoice_type = "PARTIAL_INVOICE" if is_partial_sequence else "FULL_INVOICE"

    return SplitInvoiceInfo(
        invoice_type=invoice_type,
        po_amount=po_amount,
        previously_invoiced=previously_invoiced,
        current_invoice=current_invoice_total,
        cumulative_invoiced=cumulative,
        remaining_balance=remaining,
    )

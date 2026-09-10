"""Split/partial invoice handling.

A vendor may invoice a single PO across several invoices. This module
computes cumulative-invoiced-vs-PO-amount purely from the permanent ledger
(never the temporary cache) so the numbers are correct across restarts.
"""
from __future__ import annotations

from app.duplicate.invoice_ledger import InvoiceLedger
from app.models.result import SplitInvoiceInfo
from app.rules.tolerance import check_tolerance


def evaluate_split_invoice(
    *,
    po_number_normalized: str | None,
    vendor_name_normalized: str,
    current_invoice_total: float | None,
    po_amount: float,
    tolerance_type: str,
    tolerance_value: float,
    ledger: InvoiceLedger,
) -> SplitInvoiceInfo:
    if not po_number_normalized or current_invoice_total is None:
        return SplitInvoiceInfo(invoice_type="FULL_INVOICE")

    prior_entries = ledger.get_prior_invoices_for_po(po_number_normalized, vendor_name_normalized)
    previously_invoiced = round(sum(e.total_amount or 0 for e in prior_entries), 2)
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

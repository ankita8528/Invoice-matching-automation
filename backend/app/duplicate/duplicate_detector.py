"""Duplicate detection -- runs BEFORE expensive downstream processing
(matching/validation), using only the document hash which is available
immediately after the file is received.

The vendor+invoice-number and potential-duplicate checks run later once the
invoice has been parsed (they need extracted fields), but still before PO
matching, per the pipeline order in the README.
"""
from __future__ import annotations

from app.duplicate.invoice_ledger import InvoiceLedger, LedgerEntry
from app.matching.normalization import normalize_invoice_number, normalize_vendor_name
from app.models.result import DuplicateInfo


def check_exact_document_duplicate(document_hash: str, ledger: InvoiceLedger) -> DuplicateInfo:
    entry = ledger.find_by_hash(document_hash)
    if entry:
        return DuplicateInfo(
            status="EXACT_DUPLICATE",
            matched_ledger_id=entry.id,
            reason=f"This exact PDF (SHA256 {document_hash[:12]}...) was already processed as invoice "
            f"{entry.invoice_number} on {entry.processed_at} (decision: {entry.decision}).",
        )
    return DuplicateInfo(status="NONE")


def check_field_duplicates(
    vendor_name: str | None,
    invoice_number: str | None,
    invoice_date: str | None,
    total_amount: float | None,
    ledger: InvoiceLedger,
) -> DuplicateInfo:
    vendor_norm = normalize_vendor_name(vendor_name)
    invnum_norm = normalize_invoice_number(invoice_number)

    entry = ledger.find_by_vendor_invoice_number(vendor_norm, invnum_norm)
    if entry:
        return DuplicateInfo(
            status="VENDOR_INVOICE_DUPLICATE",
            matched_ledger_id=entry.id,
            reason=f"Vendor '{vendor_name}' + invoice number '{invoice_number}' was already processed "
            f"on {entry.processed_at} (decision: {entry.decision}). If this is a legitimate correction/"
            f"revision it must be submitted with a distinct invoice number.",
        )

    potentials: list[LedgerEntry] = ledger.find_potential_duplicates(vendor_norm, total_amount, invoice_date)
    potentials = [p for p in potentials if p.invoice_number_normalized != invnum_norm]
    if potentials:
        match = potentials[0]
        return DuplicateInfo(
            status="POTENTIAL_DUPLICATE",
            matched_ledger_id=match.id,
            reason=f"Same vendor, amount ({total_amount}) and date ({invoice_date}) as a previously processed "
            f"invoice ('{match.invoice_number}', processed {match.processed_at}), but a different invoice number.",
        )

    return DuplicateInfo(status="NONE")

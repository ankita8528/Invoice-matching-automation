"""Persistent cache of processed-invoice details, keyed by matched PO number.

This single cache powers two deterministic checks -- see
services/processing_service.py for how it's wired in:

  1. Split-invoice cumulative tracking (rules/split_invoice.py): sums prior
     accepted subtotals against a PO to compute cumulative-invoiced-vs-PO-amount.
  2. Duplicate detection: an incoming invoice whose PO number, invoice
     number, subtotal, tax, total, and line items ALL match an already-cached
     invoice is rejected as a duplicate -- see find_duplicate().

It survives restarts and never expires (a PO can legitimately be invoiced
against over months). It does NOT track document hashes or vendor identity.
"""
from __future__ import annotations

import json
from dataclasses import dataclass

from app.database import db_cursor
from app.models.invoice import InvoiceLineItem

_AMOUNT_EPSILON = 0.01


def _line_items_signature(line_items: list[InvoiceLineItem]) -> str:
    """A stable, order-independent signature for a set of line items, used
    only to compare "are these the same line items" -- not for display.
    """
    rows = sorted(
        (
            (li.description or li.item_name or "").strip().lower(),
            round(li.quantity, 4) if li.quantity is not None else None,
            round(li.unit_price, 2) if li.unit_price is not None else None,
            round(li.amount, 2) if li.amount is not None else None,
        )
        for li in line_items
    )
    return json.dumps(rows)


def _amounts_match(a: float | None, b: float | None) -> bool:
    if a is None and b is None:
        return True
    if a is None or b is None:
        return False
    return abs(a - b) <= _AMOUNT_EPSILON


@dataclass
class DuplicateMatch:
    cache_id: int
    po_number_normalized: str


class POInvoiceCache:
    def insert(
        self,
        *,
        po_number_normalized: str,
        invoice_number_normalized: str | None,
        subtotal_amount: float | None,
        tax_amount: float | None,
        total_amount: float | None,
        line_items: list[InvoiceLineItem],
        decision: str,
    ) -> int:
        with db_cursor() as cur:
            cur.execute(
                "INSERT INTO po_invoice_cache "
                "(po_number_normalized, invoice_number_normalized, subtotal_amount, tax_amount, "
                " total_amount, line_items_signature, decision) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    po_number_normalized,
                    invoice_number_normalized,
                    subtotal_amount,
                    tax_amount,
                    total_amount,
                    _line_items_signature(line_items),
                    decision,
                ),
            )
            return cur.lastrowid

    def get_prior_amounts(self, po_number_normalized: str) -> list[float]:
        """Subtotals previously invoiced (and accepted, at least partially)
        against this PO, used to compute the cumulative total for split
        invoices. Only APPROVE / "Accept/partial payment" rows count.
        """
        if not po_number_normalized:
            return []
        with db_cursor() as cur:
            cur.execute(
                "SELECT subtotal_amount FROM po_invoice_cache WHERE po_number_normalized = ? "
                "AND decision IN ('APPROVE', 'Accept/partial payment')",
                (po_number_normalized,),
            )
            return [row["subtotal_amount"] or 0.0 for row in cur.fetchall()]

    def find_duplicate(
        self,
        *,
        po_number_normalized: str,
        invoice_number_normalized: str | None,
        subtotal_amount: float | None,
        tax_amount: float | None,
        total_amount: float | None,
        line_items: list[InvoiceLineItem],
    ) -> DuplicateMatch | None:
        """An invoice is a duplicate of an already-cached one for the SAME PO
        when its invoice number, subtotal, tax, total, and line items all
        match exactly (within a small rounding epsilon for amounts).
        """
        if not po_number_normalized or not invoice_number_normalized:
            return None
        signature = _line_items_signature(line_items)
        with db_cursor() as cur:
            cur.execute(
                "SELECT id, subtotal_amount, tax_amount, total_amount, line_items_signature "
                "FROM po_invoice_cache WHERE po_number_normalized = ? AND invoice_number_normalized = ?",
                (po_number_normalized, invoice_number_normalized),
            )
            for row in cur.fetchall():
                if (
                    _amounts_match(row["subtotal_amount"], subtotal_amount)
                    and _amounts_match(row["tax_amount"], tax_amount)
                    and _amounts_match(row["total_amount"], total_amount)
                    and row["line_items_signature"] == signature
                ):
                    return DuplicateMatch(cache_id=row["id"], po_number_normalized=po_number_normalized)
        return None

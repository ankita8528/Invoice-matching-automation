"""Persistent cache of (PO number, invoiced amount) used ONLY to compute
split/partial-invoice cumulative totals -- see rules/split_invoice.py.

This is deliberately minimal: no document hash, no vendor/invoice-number
identity tracking, no duplicate detection. It survives restarts and never
expires (a PO can legitimately be invoiced against over months).
"""
from __future__ import annotations

from app.database import db_cursor


class POInvoiceCache:
    def insert(self, *, po_number_normalized: str, amount: float | None, decision: str) -> int:
        with db_cursor() as cur:
            cur.execute(
                "INSERT INTO po_invoice_cache (po_number_normalized, amount, decision) VALUES (?, ?, ?)",
                (po_number_normalized, amount, decision),
            )
            return cur.lastrowid

    def get_prior_amounts(self, po_number_normalized: str) -> list[float]:
        """Amounts previously invoiced (and accepted, at least partially)
        against this PO, used to compute the cumulative total for split
        invoices. Only APPROVE/APPROVE_PARTIAL rows count.
        """
        if not po_number_normalized:
            return []
        with db_cursor() as cur:
            cur.execute(
                "SELECT amount FROM po_invoice_cache WHERE po_number_normalized = ? "
                "AND decision IN ('APPROVE', 'APPROVE_PARTIAL')",
                (po_number_normalized,),
            )
            return [row["amount"] or 0.0 for row in cur.fetchall()]

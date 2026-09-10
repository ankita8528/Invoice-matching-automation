"""Persistent invoice ledger (permanent, survives restarts and 24h+ periods)
plus a separate, genuinely expirable temporary processing cache.

Nothing financial (duplicate detection, split-invoice cumulative totals)
reads from the temporary cache -- it only ever reads `invoice_ledger`.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Optional

from app.database import db_cursor


@dataclass
class LedgerEntry:
    id: int
    invoice_id: str
    file_name: str
    vendor_name: str
    vendor_name_normalized: str
    invoice_number: str
    invoice_number_normalized: str
    invoice_date: Optional[str]
    po_number: Optional[str]
    po_number_normalized: Optional[str]
    total_amount: Optional[float]
    document_hash: str
    decision: str
    reason: str
    processed_at: str


def _row_to_entry(row) -> LedgerEntry:
    return LedgerEntry(
        id=row["id"],
        invoice_id=row["invoice_id"],
        file_name=row["file_name"],
        vendor_name=row["vendor_name"],
        vendor_name_normalized=row["vendor_name_normalized"],
        invoice_number=row["invoice_number"],
        invoice_number_normalized=row["invoice_number_normalized"],
        invoice_date=row["invoice_date"],
        po_number=row["po_number"],
        po_number_normalized=row["po_number_normalized"],
        total_amount=row["total_amount"],
        document_hash=row["document_hash"],
        decision=row["decision"],
        reason=row["reason"],
        processed_at=row["processed_at"],
    )


class InvoiceLedger:
    def find_by_hash(self, document_hash: str) -> Optional[LedgerEntry]:
        with db_cursor() as cur:
            cur.execute("SELECT * FROM invoice_ledger WHERE document_hash = ? ORDER BY id LIMIT 1", (document_hash,))
            row = cur.fetchone()
            return _row_to_entry(row) if row else None

    def find_by_vendor_invoice_number(self, vendor_name_normalized: str, invoice_number_normalized: str) -> Optional[LedgerEntry]:
        if not vendor_name_normalized or not invoice_number_normalized:
            return None
        with db_cursor() as cur:
            cur.execute(
                "SELECT * FROM invoice_ledger WHERE vendor_name_normalized = ? AND invoice_number_normalized = ? ORDER BY id LIMIT 1",
                (vendor_name_normalized, invoice_number_normalized),
            )
            row = cur.fetchone()
            return _row_to_entry(row) if row else None

    def find_potential_duplicates(
        self, vendor_name_normalized: str, total_amount: Optional[float], invoice_date: Optional[str]
    ) -> list[LedgerEntry]:
        """Same vendor + same amount + same date, but a different invoice number
        (already excluded exact-match case) -- a common near-duplicate signal.
        """
        if not vendor_name_normalized or total_amount is None:
            return []
        with db_cursor() as cur:
            cur.execute(
                "SELECT * FROM invoice_ledger WHERE vendor_name_normalized = ? AND total_amount = ? AND invoice_date = ?",
                (vendor_name_normalized, total_amount, invoice_date),
            )
            return [_row_to_entry(r) for r in cur.fetchall()]

    def get_prior_invoices_for_po(self, po_number_normalized: str, vendor_name_normalized: str) -> list[LedgerEntry]:
        if not po_number_normalized:
            return []
        with db_cursor() as cur:
            cur.execute(
                "SELECT * FROM invoice_ledger WHERE po_number_normalized = ? AND vendor_name_normalized = ? "
                "AND decision IN ('APPROVE', 'APPROVE_PARTIAL')",
                (po_number_normalized, vendor_name_normalized),
            )
            return [_row_to_entry(r) for r in cur.fetchall()]

    def insert(
        self,
        *,
        invoice_id: str,
        file_name: str,
        vendor_name: str,
        vendor_name_normalized: str,
        invoice_number: str,
        invoice_number_normalized: str,
        invoice_date: Optional[str],
        po_number: Optional[str],
        po_number_normalized: Optional[str],
        total_amount: Optional[float],
        document_hash: str,
        decision: str,
        reason: str,
        result_json: dict[str, Any],
    ) -> int:
        with db_cursor() as cur:
            cur.execute(
                """INSERT INTO invoice_ledger
                (invoice_id, file_name, vendor_name, vendor_name_normalized, invoice_number,
                 invoice_number_normalized, invoice_date, po_number, po_number_normalized,
                 total_amount, document_hash, decision, reason, result_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    invoice_id,
                    file_name,
                    vendor_name,
                    vendor_name_normalized,
                    invoice_number,
                    invoice_number_normalized,
                    invoice_date,
                    po_number,
                    po_number_normalized,
                    total_amount,
                    document_hash,
                    decision,
                    reason,
                    json.dumps(result_json, default=str),
                ),
            )
            return cur.lastrowid

    # --- Temporary processing cache (expirable; never a source of truth) ---

    def cache_set(self, key: str, payload: dict, ttl_hours: int) -> None:
        expires_at = (datetime.utcnow() + timedelta(hours=ttl_hours)).isoformat()
        with db_cursor() as cur:
            cur.execute(
                "INSERT INTO processing_cache (cache_key, payload, expires_at) VALUES (?, ?, ?) "
                "ON CONFLICT(cache_key) DO UPDATE SET payload=excluded.payload, expires_at=excluded.expires_at",
                (key, json.dumps(payload, default=str), expires_at),
            )

    def cache_get(self, key: str) -> Optional[dict]:
        with db_cursor() as cur:
            cur.execute("SELECT payload, expires_at FROM processing_cache WHERE cache_key = ?", (key,))
            row = cur.fetchone()
            if not row:
                return None
            if datetime.fromisoformat(row["expires_at"]) < datetime.utcnow():
                return None
            return json.loads(row["payload"])

    def cache_purge_expired(self) -> int:
        with db_cursor() as cur:
            cur.execute("DELETE FROM processing_cache WHERE expires_at < ?", (datetime.utcnow().isoformat(),))
            return cur.rowcount

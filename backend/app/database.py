"""SQLite connection + schema management for the permanent invoice ledger
and the (separate, expirable) temporary processing cache.

Design note: the permanent ledger table (`invoice_ledger`) must survive
application restarts and must NOT expire after 24 hours -- it is the
system of record used for duplicate detection and split-invoice cumulative
calculations. The `processing_cache` table is a short-lived helper (default
TTL 24h, configurable) and is safe to purge; nothing financial depends on it.
"""
from __future__ import annotations

import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path

from app.config import get_settings

_local = threading.local()

SCHEMA = """
CREATE TABLE IF NOT EXISTS invoice_ledger (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    invoice_id TEXT NOT NULL,
    file_name TEXT,
    vendor_name TEXT,
    vendor_name_normalized TEXT,
    invoice_number TEXT,
    invoice_number_normalized TEXT,
    invoice_date TEXT,
    po_number TEXT,
    po_number_normalized TEXT,
    total_amount REAL,
    document_hash TEXT NOT NULL,
    decision TEXT NOT NULL,
    reason TEXT,
    result_json TEXT,
    processed_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_ledger_hash ON invoice_ledger(document_hash);
CREATE INDEX IF NOT EXISTS idx_ledger_vendor_invnum ON invoice_ledger(vendor_name_normalized, invoice_number_normalized);
CREATE INDEX IF NOT EXISTS idx_ledger_po ON invoice_ledger(po_number_normalized, vendor_name_normalized);

CREATE TABLE IF NOT EXISTS processing_cache (
    cache_key TEXT PRIMARY KEY,
    payload TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    expires_at TEXT NOT NULL
);
"""


def _db_path() -> Path:
    settings = get_settings()
    path = settings.resolve(settings.database_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def get_connection() -> sqlite3.Connection:
    """Thread-local SQLite connection (SQLite connections aren't thread-safe to share).

    Reopens automatically if DATABASE_PATH changed (e.g. between tests using
    different settings) rather than silently reusing a stale connection.
    """
    target_path = str(_db_path())
    conn = getattr(_local, "conn", None)
    cached_path = getattr(_local, "path", None)
    if conn is None or cached_path != target_path:
        if conn is not None:
            conn.close()
        conn = sqlite3.connect(target_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL;")
        _local.conn = conn
        _local.path = target_path
    return conn


def init_db() -> None:
    conn = get_connection()
    conn.executescript(SCHEMA)
    conn.commit()


@contextmanager
def db_cursor():
    conn = get_connection()
    cur = conn.cursor()
    try:
        yield cur
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close()

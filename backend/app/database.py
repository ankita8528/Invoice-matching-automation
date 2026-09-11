"""SQLite connection + schema management for the persistent PO invoice cache.

Design note: this cache stores only what split-invoice cumulative tracking
needs -- the matched PO number and the invoiced amount (plus decision, to
know which rows count as "actually invoiced"). It intentionally does NOT
track document hashes, vendor/invoice-number identity, or anything else;
duplicate detection is not implemented in this system. The table must
survive application restarts and never expire -- a PO can legitimately be
invoiced against over a period of months.
"""
from __future__ import annotations

import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path

from app.config import get_settings

_local = threading.local()

SCHEMA = """
CREATE TABLE IF NOT EXISTS po_invoice_cache (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    po_number_normalized TEXT NOT NULL,
    amount REAL,
    decision TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_po_invoice_cache_po ON po_invoice_cache(po_number_normalized);
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

import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_DIR.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import pytest

from app.config import get_settings
from app.database import init_db
from app.rules.po_invoice_cache import POInvoiceCache
from app.services.data_loader import DataStore
from app.services.processing_service import ProcessingService

INVOICES_DIR = REPO_ROOT / "invoices"


@pytest.fixture()
def settings(tmp_path, monkeypatch):
    """Settings pointed at a throwaway SQLite DB per test, but the REAL
    dataset (data/purchase_orders.xlsx, data/vendors.xlsx) so tests exercise
    the actual generated dataset.

    Deliberately forces the vision provider back to a safe, offline default
    regardless of whatever a developer's real .env has configured (e.g.
    VISION_PROVIDER=huggingface with a real paid token) -- tests must never
    make live network/paid-API calls. A scanned invoice hitting an
    unreachable Ollama at this bogus port fails fast with a connection error,
    which is exactly the graceful-degradation path being tested (-> REVIEW).
    """
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "test_ledger.db"))
    monkeypatch.setenv("VISION_PROVIDER", "ollama")
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://127.0.0.1:1")
    monkeypatch.setenv("VISION_REQUEST_TIMEOUT_SECONDS", "5")
    monkeypatch.setenv("HF_API_TOKEN", "")
    get_settings.cache_clear()
    s = get_settings()
    yield s
    get_settings.cache_clear()


@pytest.fixture()
def service(settings):
    init_db()
    data_store = DataStore(settings.resolve(settings.po_file), settings.resolve(settings.vendor_file))
    cache = POInvoiceCache()
    return ProcessingService(settings, data_store, cache)


@pytest.fixture()
def invoice_bytes():
    def _load(name: str) -> bytes:
        return (INVOICES_DIR / name).read_bytes()

    return _load

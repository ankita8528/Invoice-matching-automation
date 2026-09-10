"""Centralized, environment-driven configuration.

Nothing in this project should hard-code model names, file paths, API keys,
or business thresholds outside of this module's defaults. Override anything
via a `.env` file (see `.env.example`) or real environment variables.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# Repo root = two levels up from this file (backend/app/config.py -> repo root)
REPO_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(REPO_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- Vision model (scanned invoices) ---
    vision_provider: str = "ollama"
    qwen_model: str = "qwen3-vl:8b"
    ollama_base_url: str = "http://localhost:11434"
    vision_request_timeout_seconds: int = 120

    # --- OCR ---
    tesseract_cmd: str = ""

    # --- Data sources ---
    po_file: str = "data/purchase_orders.xlsx"
    vendor_file: str = "data/vendors.xlsx"
    database_path: str = "data/invoice_ledger.db"

    # --- Optional agentic exception-handling layer ---
    enable_exception_agent: bool = False
    exception_agent_model: str = "qwen3-vl:8b"

    # --- PO matching ---
    po_match_threshold: float = 0.85
    ambiguous_match_margin: float = 0.05
    level3_weight_vendor: float = 30
    level3_weight_item: float = 30
    level3_weight_quantity: float = 15
    level3_weight_unit_price: float = 15
    level3_weight_amount: float = 10

    # --- Extraction ---
    min_text_length_for_digital: int = 40

    # --- Financial rounding tolerance for arithmetic checks ---
    arithmetic_tolerance: float = 1.0

    # --- Temporary processing cache (NOT the permanent ledger) ---
    temp_cache_ttl_hours: int = 24

    # --- API / CORS ---
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"

    log_level: str = "INFO"
    log_file: str = "logs/app.log"

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    def resolve(self, relative_path: str) -> Path:
        """Resolve a config path relative to the repo root if it isn't absolute."""
        p = Path(relative_path)
        return p if p.is_absolute() else (REPO_ROOT / p)


@lru_cache
def get_settings() -> Settings:
    return Settings()

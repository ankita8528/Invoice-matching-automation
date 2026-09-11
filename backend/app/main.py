"""FastAPI application entrypoint.

Run with:  uvicorn app.main:app --reload --app-dir backend
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.database import init_db
from app.rules.po_invoice_cache import POInvoiceCache
from app.services.data_loader import DataStore
from app.services.processing_service import ProcessingService


def configure_logging(settings) -> None:
    log_path = settings.resolve(settings.log_file)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=getattr(logging, settings.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=[logging.StreamHandler(), logging.FileHandler(log_path, encoding="utf-8")],
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    configure_logging(settings)
    init_db()

    data_store = DataStore(settings.resolve(settings.po_file), settings.resolve(settings.vendor_file))
    cache = POInvoiceCache()
    service = ProcessingService(settings, data_store, cache)

    app.state.settings = settings
    app.state.data_store = data_store
    app.state.cache = cache
    app.state.processing_service = service

    logging.getLogger("app.main").info("Startup complete. PO_FILE=%s VENDOR_FILE=%s DB=%s", settings.po_file, settings.vendor_file, settings.database_path)
    yield


def create_app() -> FastAPI:
    app = FastAPI(title="Invoice AP Matching Automation", version="1.0.0", lifespan=lifespan)

    settings = get_settings()
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    from app.api.routes import router as api_router

    app.include_router(api_router, prefix="/api")
    return app


app = create_app()

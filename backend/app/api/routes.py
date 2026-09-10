"""API layer. Deliberately thin: no business rules live here -- every
request is just "read the file, hand it to the processing service, return
whatever DecisionResult comes back". See services/processing_service.py for
the actual pipeline.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Request, UploadFile
from fastapi.responses import JSONResponse

from app.services.data_loader import DataFileMissingError

logger = logging.getLogger("app.api")

router = APIRouter()


@router.get("/health")
async def health(request: Request) -> dict:
    settings = request.app.state.settings
    return {
        "status": "ok",
        "vision_provider": settings.vision_provider,
        "qwen_model": settings.qwen_model,
        "exception_agent_enabled": settings.enable_exception_agent,
    }


@router.post("/decide")
async def decide_invoice(request: Request, file: UploadFile) -> JSONResponse:
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        return JSONResponse(status_code=422, content={"error": "Only PDF files are supported."})

    pdf_bytes = await file.read()
    if not pdf_bytes:
        return JSONResponse(status_code=422, content={"error": "Uploaded file is empty."})

    service = request.app.state.processing_service
    try:
        result = service.process_invoice(pdf_bytes, file.filename)
    except DataFileMissingError as exc:
        logger.error("Data file missing: %s", exc)
        return JSONResponse(status_code=500, content={"error": f"System configuration error: {exc}"})
    except Exception as exc:  # noqa: BLE001 - last-resort safety net, see README "Error handling"
        logger.exception("Unexpected error while processing invoice %s", file.filename)
        return JSONResponse(status_code=500, content={"error": f"Unexpected server error while processing invoice: {exc}"})

    return JSONResponse(status_code=200, content=result.model_dump(mode="json"))

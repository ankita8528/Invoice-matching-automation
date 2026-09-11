# Invoice AP Matching Automation -- backend API service.
#
# Builds a container that runs the FastAPI backend (uvicorn) with Tesseract
# OCR available on PATH. The vision model itself is NOT bundled -- point
# VISION_PROVIDER at "huggingface" (a hosted API, no local model needed) or
# "ollama" pointed at an Ollama instance reachable from this container (see
# README section 14). No secrets are baked into the image: pass HF_API_TOKEN
# etc. at `docker run` time via -e / --env-file.
FROM python:3.10-slim

# tesseract-ocr: the OCR engine for scanned invoices (see extraction/ocr.py).
# libgl1 / libglib2.0-0: common runtime deps for Pillow/PyMuPDF's image codecs
# on Debian slim images.
RUN apt-get update && apt-get install -y --no-install-recommends \
        tesseract-ocr \
        libgl1 \
        libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install dependencies before copying the rest of the source so that a
# code-only change doesn't invalidate this (slow) layer.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Application code, plus the data the app needs to run (PO/vendor master
# spreadsheets, scoring/tolerance config). Test fixtures (invoices/,
# invoice_po_matching_dataset/), the frontend, and dev tooling are
# deliberately left out of the image -- see .dockerignore.
COPY backend/ backend/
COPY data/purchase_orders.xlsx data/vendors.xlsx data/rules.yaml data/

# Runtime state directories. The PO invoice cache (data/invoice_ledger.db)
# is created here on first startup; mount a volume over /app/data in
# production so it survives container restarts/recreations (see README).
RUN mkdir -p /app/data /app/logs

RUN useradd --create-home --uid 1000 appuser && chown -R appuser:appuser /app
USER appuser

WORKDIR /app/backend
ENV PYTHONUNBUFFERED=1

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/api/health', timeout=3)" || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]

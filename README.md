# Invoice-matching-automation

An AI-assisted, **deterministic** Invoice Processing and PO-Matching system. It takes one invoice
PDF at a time (digital or scanned), extracts its fields, matches it to a purchase order, runs a
fixed set of business-rule checks, and returns an explainable `APPROVE` / `Accept/partial payment` /
`REVIEW` / `REJECT` decision with a full audit trail.

```
POST /api/decide  (multipart/form-data, field "file")  ->  JSON decision
```

## 1. What this project does

Given one invoice PDF, the system produces:

- Extracted invoice fields (vendor, invoice number/date, PO reference, line items, amounts)
- The matched PO (number, spreadsheet row, snapshot, match method, confidence)
- A set of named PASS/FAIL/WARNING/NOT_CHECKED checks (vendor approval, duplicate, PO match,
  line items, quantities, prices, tolerance, arithmetic, split-invoice, ...)
- Duplicate status, vendor status, amount/tolerance analysis, split-invoice state
- A final decision plus a human-readable reason
- A step-by-step audit/processing log

It is built to run against the real dataset shipped in `invoice_po_matching_dataset/` (12 invoices)
plus a supplementary synthetic set in `invoices/` (15 more invoices covering edge cases the
provided dataset doesn't, e.g. split invoicing and PO-number formatting variants) -- 27 invoices
in total, all wired into one integration test.

## 2. Architecture

```
Invoice PDF
    |
PDF text extraction (PyMuPDF) -- determines digital vs scanned, and supplies
    |                             the exact text as grounding context either way
Render first page to image
    |
Digital? use the extracted text as context : Scanned? run Tesseract OCR for context
    |
Qwen3-VL vision extraction (Ollama or Hugging Face Inference Providers) -- structured JSON
    |   (digital PDFs fall back to a regex/heuristic parser if the vision call itself fails;
    |    scanned PDFs have no such fallback and degrade to REVIEW)
Invoice validation (required fields, arithmetic: qty*price, subtotal+tax=total)
    |
Vendor validation (normalized name match against vendor master; approval status)
    |
PO matching (level 1: exact normalized PO number: level 2: malformed/partial PO number;
             level 3: vendor+line-item+amount candidate scoring, ranked, with a confidence
             threshold and an ambiguity margin)
    |
Invoice <-> PO checks (vendor identity, line items, quantity, unit price)
    |
Tolerance (vendor- or PO-level, percentage or absolute)
    |
Split/partial invoice handling (cumulative amount vs PO amount, from the persistent PO invoice cache)
    |
Decision engine (deterministic Python; REJECT > REVIEW > APPROVE/"Accept/partial payment" precedence)
    |
Audit log + persistent PO invoice cache (SQLite)
    |
JSON response  ->  Streamlit UI / React frontend
```

Every box above is a plain, independently-testable Python module (see `backend/app/`). The vision
model is used for BOTH digital and scanned PDFs now (see section 7 for why), but it is still never
the source of truth for arithmetic or the final decision -- its output is normalized into the same
Pydantic schema regardless of path and then runs through the *exact same* deterministic downstream
pipeline. This system does not implement duplicate detection (see section 8).

### Project layout

```
backend/
  app/
    main.py                    FastAPI app, CORS, startup (DB init, data loading)
    config.py                  All configuration (env-driven, no hardcoding)
    database.py                SQLite connection + schema
    api/routes.py               POST /api/decide, GET /api/health (no business logic here)
    extraction/                 pdf_extractor, ocr, vision_extractor, invoice_parser
    matching/                   normalization, fuzzy_matcher, po_matcher (levels 1/2/3)
    validation/                 invoice_validator, amount_validator, line_item_validator, vendor_validator
    rules/                      tolerance, split_invoice, po_invoice_cache, decision_engine
    models/                     invoice.py, po.py, result.py (Pydantic schemas)
    services/                   data_loader (PO/vendor spreadsheets), processing_service (orchestrator)
    agent/                      exception_agent.py (optional, advisory-only)
  tests/                       unit tests per module + one full-dataset integration test
frontend/                      React + Vite UI
streamlit_app.py                Streamlit showcase UI (no Node.js needed) -- see section 12
data/
  purchase_orders.xlsx         merged: real dataset's POs + supplementary synthetic POs
  vendors.xlsx                 merged vendor master
  rules.yaml                   human-readable mirror of the scoring/tolerance constants
  invoice_ledger.db            created at runtime (persistent PO invoice cache; not committed)
invoices/                      27 test invoices (real dataset copies + synthetic) + ground_truth.json
invoice_po_matching_dataset/    the REAL provided dataset, UNMODIFIED (see its own README)
scripts/generate_dataset.py    builds data/*.xlsx + invoices/* from the real dataset + synthetic cases
logs/                          app.log at runtime
```

## 3. Why GenAI is used (and where)

GenAI (a vision-language model, Qwen3-VL by default) is used for exactly one thing: **turning a
scanned/image invoice into a structured JSON guess** when there is no extractable text layer. It
receives the rendered page image plus the Tesseract OCR text and is instructed to return *only* a
JSON object matching the invoice schema, with `null` for anything it can't read reliably. That's
document understanding, not decision-making.

Optionally (`ENABLE_EXCEPTION_AGENT=true`), a second, separate LLM call can produce a short,
advisory explanation for a case that already landed on `REVIEW` -- e.g. "this looks like a
possible split invoice, check invoice #X against the same PO." It never changes the decision.

## 4. Why deterministic rules are used for everything else

Arithmetic, tolerance math, duplicate detection, PO matching thresholds, and the final decision
are all plain Python. An LLM is never asked "is this invoice okay to pay" and never asked to add
or compare numbers. This is a hard requirement from the spec and a sound one: financial decisions
need to be reproducible, auditable, and explainable after the fact, which a generative model's
output is not guaranteed to be from one run to the next.

## 5. Why this is NOT fully agentic

There is no autonomous loop deciding what to do next. `services/processing_service.py` calls a
fixed sequence of plain functions in a fixed order every time. The only optional AI-agent-like
piece (`agent/exception_agent.py`) is a single advisory call, gated by a config flag, that runs
*after* the decision is already final and cannot alter it. If it's disabled, times out, or the
model is unreachable, the pipeline behaves identically -- it just doesn't have that extra note
attached.

## 6. How scanned invoices are handled

1. `extraction/pdf_extractor.py` extracts text with PyMuPDF. If the cleaned text is shorter than
   `MIN_TEXT_LENGTH_FOR_DIGITAL` chars or is mostly non-alphanumeric, the PDF is treated as scanned.
2. The first page is rendered to a PIL image (`render_first_page_to_image`).
3. `extraction/ocr.py` runs Tesseract on that image. If Tesseract isn't installed/configured, this
   is caught (`OCRUnavailableError`) and logged -- the pipeline continues with empty OCR text rather
   than crashing.
4. `extraction/vision_extractor.py` sends the image + OCR text to Qwen3-VL via Ollama
   (`POST {OLLAMA_BASE_URL}/api/generate`, `format: "json"`), with a prompt that forbids inventing
   values and requires a single JSON object matching the invoice schema.
5. The JSON is parsed defensively (strips code fences, finds the first balanced `{...}` if the
   model added stray text) and normalized into the same `StructuredInvoice` schema as the digital
   path, tagged `"method": "tesseract_qwen3_vl"`.
6. If OCR *and* the vision call both fail to produce anything usable, the endpoint still returns
   HTTP 200 with `decision: "REVIEW"` and a reason explaining extraction failed -- never a 500.

The integration test marks all 7 scanned invoices (1 synthetic + 6 real) `environment_dependent:
true` and reports them as `SKIP(env)` rather than hard failures if extraction doesn't succeed --
see section 17 (Known limitations) and section 12 (Testing).

**Verified live on a CPU-only laptop (no discrete GPU, 16 GB RAM shared with other running apps):**
Tesseract and Ollama + `qwen3-vl:8b` were both installed and exercised end-to-end against a real
scanned invoice from the dataset. Findings, in case you hit the same thing:

- The full path works: text extraction correctly detects no usable text layer, the page renders to
  an image, Tesseract OCR runs, and the image + OCR text are sent to Qwen3-VL.
- On CPU only, a single scanned-invoice request took **~6 minutes** (image encoding alone was
  ~2.5 minutes; text generation ran at ~3.6 tokens/sec) and required close to the full 6.1 GB
  resident for the model. `VISION_REQUEST_TIMEOUT_SECONDS` defaults to 120s in `.env.example`,
  which is enough for a GPU or a lightly-loaded machine but **too short for CPU-only inference**;
  bump it (600+) if you're in that situation.
- Ollama's `format: "json"` grammar-constrained decoding was tried first and, in this environment,
  sometimes returned an empty `response` for the multimodal prompt even though the model had
  generated real tokens (visible in Ollama's own server log). `vision_extractor.py` deliberately
  does **not** set `format: "json"` for this reason -- it relies on the prompt's own JSON-only
  instruction plus the defensive `_extract_first_json_object()` repair step (strips code fences,
  finds the first balanced `{...}`), which proved more reliable in practice.
- On a memory-constrained machine, loading the model for the first inference call can push free
  RAM close to zero, which triggered this sandbox's OOM watchdog to kill the Ollama/backend
  processes outright on more than one attempt. If you hit this, close other memory-heavy
  applications before uploading a scanned invoice, or run on a machine with more headroom (a
  discrete GPU changes this picture entirely -- inference moves off system RAM and is dramatically
  faster).
- Every one of these failure modes (timeout, empty/malformed model output, OOM) is handled by the
  graceful-degradation path in `services/processing_service.py`: the request still returns HTTP 200
  with a structured `REVIEW` decision and a clear reason, never a crash or a hang from the caller's
  perspective (the OOM-killer terminating the whole server process is the one exception -- that's
  an OS-level kill, not something application code can catch).

## 7. How PO matching works

`matching/po_matcher.py`, in order:

- **Level 1 -- exact normalized match.** `matching/normalization.py` strips spaces/hyphens/slashes/
  punctuation and uppercases (`PO-1005`, `PO 1005`, `po/1005` all become `PO1005`). If the invoice's
  normalized PO number equals exactly one PO's normalized number, that's the match (confidence 1.0).
- **Level 2 -- malformed/partial reference.** If level 1 finds nothing, digits-only containment is
  tried (e.g. `Ref: 1011` -> digits `1011` matches PO `PO1011`'s digits). Confidence 0.75-0.9.
- **Level 3 -- no usable PO number.** Every PO is scored against the invoice using a configurable
  weighted blend (defaults in `.env`/`config.py`, mirrored in `data/rules.yaml`):
  `vendor_match 30 + item_similarity 30 + quantity_match 15 + unit_price_match 15 + amount_match 10`.
  The ranked candidate list is always returned. The top candidate is only used as a match if its
  score clears `PO_MATCH_THRESHOLD` (default 0.85) **and** beats the runner-up by at least
  `AMBIGUOUS_MATCH_MARGIN` (default 0.05); otherwise the result is `ambiguous`/`no_match`.

**Important policy, confirmed against the real provided dataset's ground truth
(`digital_04_missing_po.pdf`):** a level-3 candidate match is *never* enough, by itself, to
`APPROVE` -- even a perfect-looking match still routes to `REVIEW` for a human to confirm, because
the PO reference itself was missing from the invoice. This mirrors the real dataset's own rule
`R002` ("if missing, attempt candidate matching; do not auto-approve solely from vendor/amount").
Level 1/2 matches (a PO reference was present, even if malformed) can still reach `APPROVE`.

## 8. Duplicate detection

**PO-scoped, not document/vendor/invoice-number based.** `rules/po_invoice_cache.py` persists, for
every invoice matched to a PO: the PO number, invoice number, subtotal, tax, total, and a
normalized line-item signature (item/qty/price/amount, order-independent). An incoming invoice is
rejected as a duplicate only when its PO number, invoice number, and *every* amount/line-item field
exactly match an already-cached invoice for that same PO -- `REJECT`, reason `"duplicate invoice
for <PO number>"`. Two different invoice numbers billing the same PO for the same amount are NOT
flagged (that's ordinary, e.g. a corrected resubmission with a new invoice number, or two
coincidentally-equal line items) -- only a true resubmission of the identical invoice is caught.
This deliberately does not track document hashes or vendor identity independent of a PO match.

## 9. Split/partial invoice handling

`rules/split_invoice.py` sums the subtotals of prior *accepted* (`APPROVE`/`Accept/partial
payment`) cache rows for the same PO to get `previously_invoiced`, adds the current invoice's
subtotal to get `cumulative_invoiced`, and compares that to the PO's amount. If there's already a
prior invoice against that PO, or this invoice alone doesn't cover the full PO amount (within
tolerance) -- i.e. the PO's amount is more than this invoice's subtotal -- it's marked
`PARTIAL_INVOICE` and the decision is `Accept/partial payment`, reason `"split invoice for <PO
number> ..."`. The tolerance check for a partial invoice only fails on **overbilling** (cumulative
exceeds PO amount + tolerance) -- under-billing is expected mid-sequence and is not an error. See
`invoices/split_invoice_1/2/3.pdf` for a worked 40/30/30-of-100 example (all three correctly
resolve to `Accept/partial payment`).

## 10. Vendor tolerance

Each vendor in `data/vendors.xlsx` has a default `tolerance_type` (`percentage` or `absolute`) and
`tolerance_value`. A PO row can optionally override this (see the `Tolerance Type`/`Tolerance
Value` columns in `data/purchase_orders.xlsx`) -- the real provided dataset specifies tolerance
*per PO* (e.g. Delta Facilities Management is 2% on `PO1004` but 1% on `PO1006`/`PO1013`), so a
PO-level value, when present, takes precedence over the vendor's default. All arithmetic is in
`rules/tolerance.py`; nothing here is ever computed by an LLM.

## 11. API usage

```
POST /api/decide
Content-Type: multipart/form-data
field: file=<invoice.pdf>
```

```bash
curl -X POST http://localhost:8000/api/decide \
  -F "file=@invoices/price_mismatch.pdf"
```

Returns **HTTP 200** for every successfully-processed invoice, including `REVIEW` and `REJECT`
outcomes. HTTP 4xx/5xx is reserved for actual processing/system errors (not a PDF, empty file,
missing PO/vendor spreadsheet, etc.) -- see `api/routes.py`.

`GET /api/health` reports the configured vision provider/model and whether the exception agent is
enabled.

### Example response (`price_mismatch.pdf`, abridged)

```json
{
  "decision": "REVIEW",
  "reason": "Unit price mismatch: '42U Server Rack Unit': invoice unit_price 43333.33 vs PO 40000.0",
  "checks": {
    "vendor_approved": { "status": "PASS", "reason": "Vendor 'BrightTech Solutions Pvt Ltd' is APPROVED (matched via exact_normalized, confidence 1.00)." },
    "po_match": { "status": "PASS", "expected": "PO2009", "actual": "PO2009", "reason": "Invoice PO reference 'PO2009' normalized to 'PO2009' matched PO PO2009 exactly." },
    "quantity_match": { "status": "PASS", "expected": 3.0, "actual": 3.0, "difference": 0.0 },
    "unit_price_match": { "status": "FAIL", "reason": "Unit price mismatch: '42U Server Rack Unit': invoice unit_price 43333.33 vs PO 40000.0" },
    "tolerance_check": { "status": "FAIL", "expected": 120000.0, "actual": 130000.0, "difference": 10000.0, "reason": "... exceeding the allowed percentage tolerance of 2400.0." }
  },
  "matched_po": {
    "po_number": "PO2009", "spreadsheet_row": 10, "vendor": "BrightTech Solutions Pvt Ltd",
    "match_method": "exact_normalized_po", "match_confidence": 1.0
  },
  "amount_analysis": { "invoice_total": 130000.0, "po_total": 120000.0, "difference": 10000.0, "allowed_tolerance": 2400.0 },
  "audit": { "processing_steps": ["Invoice received: price_mismatch.pdf", "SHA256 calculated: ...", "..."] }
}
```

## 12. Frontend usage

Two UIs, both pure clients of `POST /api/decide` with no business logic of their own:

- **`streamlit_app.py`** -- the UI actually used/verified throughout this project's development
  (no Node.js needed: `streamlit run streamlit_app.py`). Shows the PDF preview alongside a colored
  decision badge (🟢 APPROVE / 🔵 Accept/partial payment / 🟡 REVIEW / 🔴 REJECT), the extracted
  values, and a collapsible "Full details" section (matched PO, all checks, audit trail, raw JSON).
- **`frontend/`** -- a React + Vite app with the same information: an upload button, decision
  badge, invoice details, matched-PO details, a checks list (failed checks are visually distinct),
  and a collapsible audit trail. Calls `VITE_API_BASE_URL` (default `http://localhost:8000`).

> **Note on this sandbox:** the environment this was built in has no Node.js/npm installed, so the
> frontend could not be `npm install`'d or run here. The backend was fully verified instead (unit
> tests, the full-dataset integration test, and live `curl` requests against a running
> `uvicorn` server). The React code follows standard Vite conventions and should run with a normal
> `npm install && npm run dev` on a machine with Node -- see section 13.

## 13. Environment setup

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate   |   macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
copy .env.example .env      # or: cp .env.example .env
python scripts/generate_dataset.py   # builds data/*.xlsx + invoices/* (safe to re-run)
```

Run the backend:

```bash
cd backend
uvicorn app.main:app --reload --port 8000
```

Run the frontend (requires Node.js 18+):

```bash
cd frontend
npm install
copy .env.example .env
npm run dev
```

## 14. Qwen / Ollama / Hugging Face setup

The vision provider is configurable (`VISION_PROVIDER`): `ollama` (local, default/preferred) or
`huggingface` (Hugging Face Inference Providers, a hosted API). No API keys are hard-coded
anywhere in either path.

### Option A -- Ollama (local, preferred)

```bash
# https://ollama.com
ollama pull qwen3-vl:8b
ollama serve   # default http://localhost:11434
```

Set in `.env`:

```
VISION_PROVIDER=ollama
QWEN_MODEL=qwen3-vl:8b
OLLAMA_BASE_URL=http://localhost:11434
```

If Ollama isn't running or the model isn't pulled, scanned-invoice requests degrade gracefully to
`REVIEW` (see section 6) instead of failing the request.

**When to prefer this:** you have a GPU, or you're fine with local CPU inference. Verified
end-to-end on this project's own CPU-only dev machine (see section 6) -- it works, but a single
scanned invoice took ~6 minutes and nearly exhausted 16GB of RAM.

### Option B -- Hugging Face Inference Providers (hosted API)

No local model download, no local compute/memory cost -- inference runs on HF's infrastructure.
Useful exactly when Option A's CPU/RAM cost isn't acceptable.

1. Create a token with **Inference Providers** permission at
   https://huggingface.co/settings/tokens.
2. Set in `.env` (never commit a real token):

```
VISION_PROVIDER=huggingface
HF_API_TOKEN=hf_your_token_here
HF_VISION_MODEL=Qwen/Qwen3-VL-8B-Instruct
HF_ROUTER_BASE_URL=https://router.huggingface.co/v1
```

This calls HF's OpenAI-compatible chat-completions endpoint
(`POST {HF_ROUTER_BASE_URL}/chat/completions`, `Authorization: Bearer <token>`) with the image as a
base64 `data:` URI in the message content, per
https://huggingface.co/docs/inference-providers/en/tasks/chat-completion . `HF_VISION_MODEL` can
include a `:provider` suffix (e.g. `Qwen/Qwen3-VL-8B-Instruct:featherless-ai`) to pin a specific
backing provider; without one, HF routes to whichever provider currently serves the model.
Deliberately does **not** use `format`/structured-output constraints here (see the note on Ollama's
equivalent option in section 6) -- it relies on the prompt's own JSON-only instruction plus the
same defensive JSON-repair parsing used for Ollama.

If `HF_API_TOKEN` is missing, or the request fails/times out, this degrades gracefully to `REVIEW`
exactly like the Ollama path -- never a crash.

## 15. Tesseract setup

```
# Windows: install from https://github.com/UB-Mannheim/tesseract/wiki, then in .env:
TESSERACT_CMD=C:\Program Files\Tesseract-OCR\tesseract.exe

# macOS: brew install tesseract
# Debian/Ubuntu: apt-get install tesseract-ocr
# (leave TESSERACT_CMD blank if tesseract is already on PATH)
```

## 16. Running tests

```bash
cd backend
pytest -q          # unit tests for every module + the full-dataset integration test
pytest -q -s tests/test_integration_dataset.py   # just the dataset table (see below)
```

39 tests total. The integration test processes all 27 invoices in `invoices/` and prints an
`invoice | expected | actual | PASS/FAIL` table, e.g.:

```
invoice                          expected         actual           result
-------------------------------------------------------------------------
digital_01_clean_exact.pdf        APPROVE          APPROVE          PASS
digital_02_price_mismatch.pdf     REVIEW           REVIEW           PASS
digital_04_missing_po.pdf         REVIEW           REVIEW           PASS
scanned_01_exact_match.pdf        APPROVE          REVIEW           SKIP(env)
split_invoice_1.pdf               Accept/partial payment  Accept/partial payment  PASS
unapproved_vendor.pdf             REJECT           REJECT           PASS
...
```

`SKIP(env)` rows are the 7 scanned invoices, which require Tesseract + Ollama to extract fields
(see section 6); every non-scanned case passes deterministically.

## 17. Dataset structure

- **`invoice_po_matching_dataset/`** -- the real dataset provided for this project, copied
  verbatim (12 invoice PDFs: 6 digital + 6 scanned; a workbook with `purchase_orders`,
  `vendor_master`, `invoice_ground_truth`, `matching_rules`, `candidate_matches`, and
  `expected_processing_log` sheets). **Never modified** -- see its own `README.md`.
- **`invoices/`** -- copies of those 12 real invoices, PLUS 15 supplementary synthetic invoices
  this project generated to cover cases the real dataset doesn't (split/partial invoicing across
  3 invoices, a PO-number formatting variant, a malformed PO reference, bundled line items) --
  27 files total, plus `ground_truth.json` (expected decision + provenance for each).
- **`data/purchase_orders.xlsx`** / **`data/vendors.xlsx`** -- built by
  `scripts/generate_dataset.py`, merging the real dataset's PO/vendor facts with the supplementary
  synthetic POs (renumbered `PO2xxx` to avoid colliding with the real dataset's `PO1xxx`/`PO9998`).

Re-run `python scripts/generate_dataset.py` any time to rebuild `data/*.xlsx` and the synthetic
invoices from scratch (idempotent; the real invoice PDFs are only copied, never regenerated).

## 18. Known limitations

- **Digital-text parsing is heuristic, not a general table/layout engine.** It handles a real
  range of label wording and layouts (single "Label: value" lines, several packed onto one line,
  bare column-header rows followed by a positionally-aligned data row) and a line-item table
  keyed off a `Description...Qty...`-style header (pipe-delimited or whitespace-column-aligned),
  because that's what both the provided and synthetic invoices use. A genuinely arbitrary layout
  (e.g. a scanned-looking table with merged cells, or right-to-left column order) is not guaranteed
  to parse correctly with a digital text layer -- that's what the OCR+vision path is for.
- **OCR/vision were verified live but not exhaustively** -- see section 6 for the full account.
  Tesseract + Ollama + `qwen3-vl:8b` were installed and run end-to-end against a real scanned
  invoice on CPU-only hardware: the path works (correct scanned-PDF detection, OCR, image+text sent
  to the model), but a single request took ~6 minutes and required close to the full model size in
  RAM, and repeated attempts triggered this sandbox's OOM watchdog on a memory-constrained machine.
  Not all 7 scanned invoices in the dataset were run to a final decision because of the time/memory
  cost per attempt; a machine with a GPU or more free RAM should be materially faster and more
  stable, and is the recommended way to validate this path against the full dataset.
- **Vendor fuzzy-matching floor (0.90) and item-similarity floor (0.55) are fixed constants**, not
  yet exposed via `.env`, since the dataset didn't require tuning them.
- **Quantity checks only catch overbilling** (invoicing more than the PO), by design, so that
  legitimate partial/split invoices aren't flagged -- see section 9. A non-split invoice that
  under-bills quantity by mistake will not fail this specific check (it will still show up as a
  `PARTIAL_INVOICE` with a nonzero remaining balance in the response, which is visible but not a
  hard failure).
- **The frontend was not run/tested** in this sandbox (no Node.js available) -- see section 12.
- **Single-page rendering for scanned PDFs**: only the first page is rendered to an image for
  OCR/vision; a multi-page scanned invoice's later pages are not currently processed.

## 19. Future improvements

- A general-purpose table extraction layer (e.g. column-position clustering) instead of the
  current header-keyword + delimiter heuristics, for arbitrary digital layouts.
- Expose the fuzzy-matching floors and level-3 scoring weights via `.env`/`rules.yaml` fully (the
  weights already are; the match floors in `validation/line_item_validator.py` and
  `validation/vendor_validator.py` aren't yet).
- Multi-page invoice/PO support (multiple invoices or continuation pages in one PDF).
- A small admin view (backed by the existing `invoice_ledger` table) to browse processed invoices,
  their decisions, and re-open a `REVIEW` case with the original PDF.
- Swap in a real embeddings model for `item_similarity` instead of `rapidfuzz` token-based scoring,
  for descriptions that are semantically similar but lexically very different.

## 20. Engineering principles this project follows

1. Deterministic financial calculations only (Python), never an LLM.
2. LLMs are used solely for document understanding (scanned-invoice extraction) and, optionally,
   advisory explanations of already-final `REVIEW` cases.
3. Every decision is explainable: a `reason` string plus a full `checks` breakdown.
4. Every important step is logged (`audit.processing_steps`, plus Python `logging`).
5. Missing fields are `null`, never invented.
6. Original spreadsheet row numbers are preserved and returned alongside a full PO snapshot.
7. The persistent PO invoice cache (used for split-invoice tracking) survives restarts and is not
   time-limited -- a PO can legitimately be invoiced against over months.
8. Every module under `backend/app/` is independently unit-testable (see `backend/tests/`).
9. All configuration is environment-driven (`.env`/`config.py`); nothing is hardcoded, no secrets
   are committed.
10. Ambiguous cases are never silently approved -- see sections 7 and 9.

## 21. Docker deployment

`Dockerfile` builds the backend API only (not the frontend/Streamlit demo UIs). It installs
Tesseract OCR (on PATH, so `TESSERACT_CMD` can stay blank), bakes in `data/purchase_orders.xlsx`,
`data/vendors.xlsx`, and `data/rules.yaml`, and runs as a non-root user. No secrets are baked into
the image -- `.env` is excluded via `.dockerignore`; pass real config at `docker run`/`docker
compose` time.

```bash
docker build -t invoice-ap-matching .

docker run -p 8000:8000 \
  --env-file .env \
  -v "$(pwd)/data:/app/data" \
  -v "$(pwd)/logs:/app/logs" \
  invoice-ap-matching
```

or with the included `docker-compose.yml` (reads `.env` and bind-mounts `data/`/`logs/` for you):

```bash
docker compose up --build
```

Then verify:

```bash
curl http://localhost:8000/api/health
curl -X POST http://localhost:8000/api/decide -F "file=@invoices/exact_match.pdf"
```

For a genuine `VISION_PROVIDER=huggingface` deployment (no local model/GPU needed), just make sure
`HF_API_TOKEN` is set in the environment passed to the container -- never in the image. For
`VISION_PROVIDER=ollama`, `OLLAMA_BASE_URL=http://localhost:11434` in `.env.example` refers to
*inside the container*; point it at wherever Ollama is actually reachable from there (e.g. a
sibling container's service name in `docker-compose.yml`, or `http://host.docker.internal:11434`
on Docker Desktop for the host machine).

**Persisting the PO invoice cache**: `data/invoice_ledger.db` (see section 9) is created at
startup and must survive container restarts/recreations. The compose file bind-mounts `./data`
directly, which also works for local testing since the repo's real `data/*.xlsx` files are already
there. If you ship the image to a server *without* this repo alongside it, use a named volume
instead of a bind mount for `/app/data` -- Docker seeds a named volume from the image's own
directory contents on first use, whereas a bind mount to an empty host path would shadow the
baked-in PO/vendor spreadsheets with nothing. See the comment in `docker-compose.yml`.

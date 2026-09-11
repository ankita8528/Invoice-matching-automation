"""Deterministic parsing of digital-PDF text into a StructuredInvoice, and
normalization of vision-model JSON into the same schema.

The digital-text parser is regex/heuristic based on purpose -- no LLM is
used to read digital PDFs, only to understand scanned ones (see
vision_extractor.py). It's tolerant of a range of label wording/layout
variants (single "Label: value" lines, several such pairs packed onto one
line, and bare column-header rows followed by a positionally-aligned data
row) so it can handle differently-worded/laid-out invoices, but it does not
attempt fully general table-layout inference (see README "Known limitations").
"""
from __future__ import annotations

import re

from dateutil import parser as dateutil_parser

from app.models.invoice import ExtractionMetadata, InvoiceDetails, InvoiceLineItem, PaymentDetails, StructuredInvoice

_NUMBER_CLEAN_RE = re.compile(r"[^\d.\-]")
_NULL_TOKENS = {"", "n/a", "na", "-", "--", "—", "–", "none", "null", "nil"}


def _parse_number(raw: str | None) -> float | None:
    if raw is None:
        return None
    cleaned = _NUMBER_CLEAN_RE.sub("", raw.strip())
    if cleaned in ("", "-", "."):
        return None
    try:
        return round(float(cleaned), 2)
    except ValueError:
        return None


def _clean_value(raw: str | None) -> str | None:
    """Strips a raw extracted string and turns placeholder "missing" tokens
    (N/A, -, em dash, ...) into None rather than treating them as real data.
    """
    if raw is None:
        return None
    cleaned = raw.strip()
    if cleaned.lower() in _NULL_TOKENS:
        return None
    return cleaned or None


def _parse_date(raw: str | None) -> str | None:
    cleaned = _clean_value(raw)
    if not cleaned:
        return None
    try:
        dt = dateutil_parser.parse(cleaned, dayfirst=False, fuzzy=False)
        return dt.strftime("%Y-%m-%d")
    except (ValueError, OverflowError):
        return None


def _first_match(patterns: list[str], text: str) -> str | None:
    for pattern in patterns:
        m = re.search(pattern, text, re.IGNORECASE | re.MULTILINE)
        if m:
            return m.group(1).strip()
    return None


# Fallback single-label regexes, tried only for whatever _extract_header_fields
# (below) doesn't resolve via the more general label/column-table scan.
INVOICE_NUMBER_PATTERNS = [
    r"Invoice\s*(?:Number|No\.?|#)\s*[:\-]\s*([A-Za-z0-9\-\/]+)",
    r"Inv\s*(?:No\.?|#)\s*[:\-]\s*([A-Za-z0-9\-\/]+)",
]
INVOICE_DATE_PATTERNS = [
    r"Invoice\s*Date\s*[:\-]\s*([0-9A-Za-z,\-\/ ]+?)(?:\n|$)",
    r"^Date\s*[:\-]\s*([0-9A-Za-z,\-\/ ]+?)(?:\n|$)",
]
PO_NUMBER_PATTERNS = [
    r"P\.?O\.?\s*(?:Number|No\.?|#|Ref(?:erence)?)\s*[:\-]\s*([A-Za-z0-9\-\/ ]+?)(?:\n|$)",
    r"Purchase\s*Order\s*(?:Number|No\.?|#)?\s*[:\-]\s*([A-Za-z0-9\-\/ ]+?)(?:\n|$)",
]
VENDOR_PATTERNS = [
    r"Vendor\s*(?:Name)?\s*[:\-]\s*(.+?)(?:\n|$)",
    r"^From\s*[:\-]\s*(.+?)(?:\n|$)",
    r"Bill\s*From\s*[:\-]\s*(.+?)(?:\n|$)",
]
SUBTOTAL_PATTERNS = [r"Sub\s*[- ]?[Tt]otal\s*[:\-]?\s*([₹$€,0-9.\-]+)"]
TAX_PATTERNS = [r"(?:Tax|GST|VAT)(?:\s*\([^)]*\))?\s*[:\-]?\s*([₹$€,0-9.\-]+)"]
TOTAL_PATTERNS = [
    r"Grand\s*Total\s*[:\-]?\s*([₹$€,0-9.\-]+)",
    r"Total\s*Amount\s*(?:Due)?\s*[:\-]?\s*([₹$€,0-9.\-]+)",
    r"Amount\s*Due\s*[:\-]?\s*([₹$€,0-9.\-]+)",
    r"^Total\s*[:\-]?\s*([₹$€,0-9.\-]+)",
]

HEADER_HINT_RE = re.compile(r"item.*qty|item.*quantity|description.*qty", re.IGNORECASE)
LINE_ITEM_ROW_RE = re.compile(r"^(.+?)\|(.*?)\|(.+?)\|(.+?)\|(.+)$")
_MULTISPACE_RE = re.compile(r"\s{2,}")
_LABELED_SEGMENT_RE = re.compile(r"^(.+?)\s*[:\-]\s*(.+)$")


def _is_date_label(label: str) -> bool:
    l = label.lower()
    return "date" in l or "issued" in l


def _is_po_label(label: str) -> bool:
    l = label.lower()
    return bool(re.search(r"\bpo\b|\bref\b|\breference\b|purchase\s*order", l))


def _is_invoice_number_label(label: str) -> bool:
    l = label.lower()
    return bool(re.search(r"\binvoice\b|\binv\b|\bbill\b|\bnumber\b", l))


def _classify_label(label: str) -> str | None:
    """Order matters: check date first ('Invoice Date' must not be read as an
    invoice-number label), then PO, then invoice-number (broadest/last).
    """
    if _is_date_label(label):
        return "invoice_date"
    if _is_po_label(label):
        return "po_number"
    if _is_invoice_number_label(label):
        return "invoice_number"
    return None


def _extract_header_fields(text: str) -> dict[str, str]:
    """Extracts invoice_number / invoice_date / po_number from whatever of
    these layouts is present:
      - one or more "Label: Value" pairs on a single line (2+ space separated)
      - such pairs spread across separate lines
      - a bare column-header row (e.g. "Invoice #   Invoice Date   PO Reference")
        immediately followed by a positionally-aligned data row
    First occurrence in reading order wins for each field.
    """
    found: dict[str, str] = {}
    lines = text.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        if not line:
            i += 1
            continue
        segments = [s for s in _MULTISPACE_RE.split(line) if s.strip()]

        pairs_found = False
        header_only_fields: list[str | None] = []
        for seg in segments:
            m = _LABELED_SEGMENT_RE.match(seg)
            if m:
                label, value = m.group(1).strip(), m.group(2).strip()
                field = _classify_label(label)
                if field and field not in found:
                    found[field] = value
                    pairs_found = True
            else:
                header_only_fields.append(_classify_label(seg))

        # Require >=2 columns so a single ordinary line (e.g. an address or
        # email that happens to contain a keyword substring) can't be
        # misread as a bare one-column "header" for the line after it.
        if not pairs_found and len(header_only_fields) >= 2 and all(header_only_fields) and len(set(header_only_fields)) == len(header_only_fields):
            if i + 1 < len(lines):
                data_segments = [s.strip() for s in _MULTISPACE_RE.split(lines[i + 1].strip()) if s.strip()]
                if len(data_segments) == len(header_only_fields):
                    for field, value in zip(header_only_fields, data_segments):
                        if field and field not in found:
                            found[field] = value
                    i += 1  # consume the data row too
        i += 1
    return found


def _parse_line_items(lines: list[str]) -> list[InvoiceLineItem]:
    items: list[InvoiceLineItem] = []
    in_table = False
    for line in lines:
        stripped = line.strip()
        if not in_table:
            if HEADER_HINT_RE.search(stripped):
                in_table = True
            continue
        if not stripped or stripped.lower().startswith(("subtotal", "sub total", "sub-total")):
            break

        if "|" in stripped:
            m = LINE_ITEM_ROW_RE.match(stripped)
            if not m:
                continue
            item_name, description, qty, unit_price, amount = (g.strip() for g in m.groups())
        else:
            tokens = [t for t in _MULTISPACE_RE.split(stripped) if t.strip()]
            if len(tokens) < 4:
                continue
            item_name = description = tokens[0]
            qty, unit_price, amount = tokens[1], tokens[2], tokens[3]

        items.append(
            InvoiceLineItem(
                item_name=item_name or None,
                description=description or None,
                quantity=_parse_number(qty),
                unit_price=_parse_number(unit_price),
                amount=_parse_number(amount),
            )
        )
    return items


def parse_digital_text(text: str) -> StructuredInvoice:
    lines = text.splitlines()
    header_fields = _extract_header_fields(text)

    invoice_number = _clean_value(header_fields.get("invoice_number")) or _first_match(INVOICE_NUMBER_PATTERNS, text)
    invoice_date_raw = _clean_value(header_fields.get("invoice_date")) or _first_match(INVOICE_DATE_PATTERNS, text)
    invoice_date = _parse_date(invoice_date_raw)
    po_number = _clean_value(header_fields.get("po_number")) or _first_match(PO_NUMBER_PATTERNS, text)
    vendor_name = _first_match(VENDOR_PATTERNS, text)

    if not vendor_name:
        for line in lines:
            candidate = line.strip()
            if candidate and not re.search(r"\binvoice\b", candidate, re.IGNORECASE) and len(candidate) > 2:
                vendor_name = candidate
                break

    subtotal = _parse_number(_first_match(SUBTOTAL_PATTERNS, text))
    tax = _parse_number(_first_match(TAX_PATTERNS, text))
    total = _parse_number(_first_match(TOTAL_PATTERNS, text))

    line_items = _parse_line_items(lines)

    required_present = sum(
        1 for v in (invoice_number, invoice_date, vendor_name, total) if v
    ) + (1 if line_items else 0)
    confidence = round(required_present / 5.0, 2)

    return StructuredInvoice(
        invoice_details=InvoiceDetails(
            vendor_name=vendor_name,
            invoice_number=invoice_number,
            invoice_date=invoice_date,
            po_number=po_number,
        ),
        line_items=line_items,
        payment_details=PaymentDetails(subtotal_amount=subtotal, tax_amount=tax, total_amount=total),
        extraction_metadata=ExtractionMetadata(method="pymupdf", confidence=confidence),
    )


def normalize_vision_json(data: dict, *, method: str = "tesseract_qwen3_vl") -> StructuredInvoice:
    """Normalize (possibly partial/messy) vision-model JSON into StructuredInvoice.
    Never invents values -- anything missing/malformed becomes None.
    """
    details = data.get("invoice_details") or {}
    payment = data.get("payment_details") or {}
    raw_items = data.get("line_items") or []

    line_items = []
    for raw in raw_items:
        if not isinstance(raw, dict):
            continue
        line_items.append(
            InvoiceLineItem(
                item_name=_coerce_str(raw.get("item_name")),
                description=_coerce_str(raw.get("description")),
                quantity=_coerce_float(raw.get("quantity")),
                unit_price=_coerce_float(raw.get("unit_price")),
                amount=_coerce_float(raw.get("amount")),
            )
        )

    required_present = sum(
        1
        for v in (
            details.get("vendor_name"),
            details.get("invoice_number"),
            details.get("invoice_date"),
            payment.get("total_amount"),
        )
        if v
    ) + (1 if line_items else 0)
    confidence = round(required_present / 5.0, 2)

    return StructuredInvoice(
        invoice_details=InvoiceDetails(
            vendor_name=_coerce_str(details.get("vendor_name")),
            invoice_number=_coerce_str(details.get("invoice_number")),
            invoice_date=_parse_date(_coerce_str(details.get("invoice_date"))),
            po_number=_coerce_str(details.get("po_number")),
        ),
        line_items=line_items,
        payment_details=PaymentDetails(
            subtotal_amount=_coerce_float(payment.get("subtotal_amount")),
            tax_amount=_coerce_float(payment.get("tax_amount")),
            total_amount=_coerce_float(payment.get("total_amount")),
        ),
        extraction_metadata=ExtractionMetadata(method=method, confidence=confidence),
    )


def merge_structured_invoices(primary: StructuredInvoice, fallback: StructuredInvoice) -> StructuredInvoice:
    """Fills any gaps in `primary` (the vision-model result, for a digital PDF)
    from `fallback` (the deterministic regex parser's result on the same
    document), field by field. Vision-model API calls occasionally succeed
    but return thin/empty data for a document it should have read perfectly
    (transient provider flakiness, not a real extraction failure -- see
    README section 6/7) -- this keeps that from silently degrading a digital
    invoice that the deterministic parser would have gotten exactly right.
    """
    pd, fd = primary.invoice_details, fallback.invoice_details
    pp, fp = primary.payment_details, fallback.payment_details

    merged_details = InvoiceDetails(
        vendor_name=pd.vendor_name or fd.vendor_name,
        invoice_number=pd.invoice_number or fd.invoice_number,
        invoice_date=pd.invoice_date or fd.invoice_date,
        po_number=pd.po_number or fd.po_number,
    )
    merged_payment = PaymentDetails(
        subtotal_amount=pp.subtotal_amount if pp.subtotal_amount is not None else fp.subtotal_amount,
        tax_amount=pp.tax_amount if pp.tax_amount is not None else fp.tax_amount,
        total_amount=pp.total_amount if pp.total_amount is not None else fp.total_amount,
    )
    merged_line_items = primary.line_items or fallback.line_items

    required_present = sum(
        1 for v in (merged_details.vendor_name, merged_details.invoice_number, merged_details.invoice_date, merged_payment.total_amount) if v
    ) + (1 if merged_line_items else 0)
    confidence = round(required_present / 5.0, 2)

    used_fallback = merged_details != pd or merged_payment != pp or merged_line_items is not primary.line_items
    method = f"{primary.extraction_metadata.method}+pymupdf_fallback" if used_fallback else primary.extraction_metadata.method

    return StructuredInvoice(
        invoice_details=merged_details,
        line_items=merged_line_items,
        payment_details=merged_payment,
        extraction_metadata=ExtractionMetadata(method=method, confidence=confidence),
    )


def _coerce_float(value) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        return _parse_number(value)
    return None


def _coerce_str(value) -> str | None:
    """Vision models sometimes emit a number where a string field (invoice
    number, PO number, ...) was asked for (e.g. 4022 instead of "4022").
    Coerce rather than let a downstream Pydantic validation crash turn an
    extraction quirk into an unhandled 500.
    """
    if value is None:
        return None
    if isinstance(value, str):
        return value
    if isinstance(value, (int, float)):
        return str(value)
    return None

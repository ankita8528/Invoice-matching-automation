from app.extraction.invoice_parser import merge_structured_invoices, normalize_vision_json, parse_digital_text
from app.extraction.pdf_extractor import extract_text


def test_digital_pdf_extraction_finds_meaningful_text(invoice_bytes):
    extracted = extract_text(invoice_bytes("exact_match.pdf"), min_length_for_digital=40)
    assert extracted.is_meaningful
    assert "Apex Office Supplies" in extracted.text


def test_scanned_pdf_has_no_meaningful_text(invoice_bytes):
    extracted = extract_text(invoice_bytes("scanned_invoice.pdf"), min_length_for_digital=40)
    assert not extracted.is_meaningful


def test_parsed_digital_invoice_fields(invoice_bytes):
    extracted = extract_text(invoice_bytes("exact_match.pdf"), min_length_for_digital=40)
    invoice = parse_digital_text(extracted.text)
    assert invoice.invoice_details.vendor_name == "Apex Office Supplies Pvt Ltd"
    assert invoice.invoice_details.invoice_number == "INV-2001"
    assert invoice.invoice_details.invoice_date == "2026-01-15"
    assert invoice.invoice_details.po_number == "PO2001"
    assert len(invoice.line_items) == 1
    assert invoice.line_items[0].quantity == 100
    assert invoice.line_items[0].unit_price == 250.00
    assert invoice.payment_details.total_amount == 25000.00


def test_parsed_digital_invoice_alternate_layout(invoice_bytes):
    extracted = extract_text(invoice_bytes("different_layout.pdf"), min_length_for_digital=40)
    invoice = parse_digital_text(extracted.text)
    assert invoice.invoice_details.vendor_name == "Apex Office Supplies Pvt Ltd"
    assert invoice.invoice_details.invoice_number == "INV-2010"
    assert invoice.invoice_details.po_number == "PO2008"
    assert invoice.payment_details.total_amount == 80000.00


def test_missing_fields_are_none_not_hallucinated(invoice_bytes):
    extracted = extract_text(invoice_bytes("missing_date.pdf"), min_length_for_digital=40)
    invoice = parse_digital_text(extracted.text)
    assert invoice.invoice_details.invoice_date is None


def test_normalize_vision_json_coerces_numeric_fields_to_strings():
    """Regression test: a vision model returning a bare number for a string
    field (e.g. invoice_number: 4022 instead of "4022") must not crash
    Pydantic validation -- it should be coerced, not turn into an unhandled 500.
    """
    raw = {
        "invoice_details": {
            "vendor_name": "Acme Corp",
            "invoice_number": 4022,
            "invoice_date": 20260910,
            "po_number": 1009,
        },
        "line_items": [{"item_name": 42, "description": "Widget", "quantity": 1, "unit_price": 10, "amount": 10}],
        "payment_details": {"subtotal_amount": 10, "tax_amount": 0, "total_amount": 10},
    }
    invoice = normalize_vision_json(raw)
    assert invoice.invoice_details.invoice_number == "4022"
    assert invoice.invoice_details.po_number == "1009"
    assert invoice.line_items[0].item_name == "42"


def test_merge_fills_gaps_from_fallback_when_vision_result_is_thin(invoice_bytes):
    """Regression test: transient vision-provider flakiness can return a
    thin/empty (but well-formed) result for a digital PDF the deterministic
    parser would have read perfectly. Merging must recover the full invoice
    rather than silently accepting the worse result.
    """
    extracted = extract_text(invoice_bytes("exact_match.pdf"), min_length_for_digital=40)
    regex_invoice = parse_digital_text(extracted.text)

    thin_vision_result = normalize_vision_json({"invoice_details": {}, "line_items": [], "payment_details": {}}, method="pymupdf_qwen3_vl")
    assert thin_vision_result.extraction_metadata.confidence == 0.0

    merged = merge_structured_invoices(thin_vision_result, regex_invoice)
    assert merged.invoice_details.vendor_name == "Apex Office Supplies Pvt Ltd"
    assert merged.invoice_details.invoice_number == "INV-2001"
    assert merged.payment_details.total_amount == 25000.00
    assert merged.extraction_metadata.confidence == 1.0
    assert "pymupdf_fallback" in merged.extraction_metadata.method


def test_merge_prefers_vision_fields_when_present():
    vision = normalize_vision_json(
        {"invoice_details": {"vendor_name": "Vision Vendor"}, "line_items": [], "payment_details": {}}, method="pymupdf_qwen3_vl"
    )
    fallback = normalize_vision_json(
        {"invoice_details": {"vendor_name": "Regex Vendor", "invoice_number": "INV-1"}, "line_items": [], "payment_details": {}}
    )
    merged = merge_structured_invoices(vision, fallback)
    assert merged.invoice_details.vendor_name == "Vision Vendor"  # vision's value wins
    assert merged.invoice_details.invoice_number == "INV-1"  # gap filled from fallback

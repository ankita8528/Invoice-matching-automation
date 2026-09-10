from app.extraction.invoice_parser import parse_digital_text
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

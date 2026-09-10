from app.matching.normalization import normalize_invoice_number, normalize_vendor_name


def test_exact_document_duplicate_rejected(service, invoice_bytes):
    pdf = invoice_bytes("exact_match.pdf")
    first = service.process_invoice(pdf, "exact_match.pdf")
    assert first.decision != "REJECT"

    second = service.process_invoice(pdf, "exact_match.pdf")
    assert second.decision == "REJECT"
    assert second.duplicate.status == "EXACT_DUPLICATE"


def test_vendor_invoice_number_duplicate_rejected(service):
    from app.duplicate.duplicate_detector import check_field_duplicates
    from app.duplicate.invoice_ledger import InvoiceLedger

    ledger = InvoiceLedger()
    vendor = "Apex Office Supplies Pvt Ltd"
    ledger.insert(
        invoice_id="INV-9001", file_name="prior.pdf", vendor_name=vendor,
        vendor_name_normalized=normalize_vendor_name(vendor), invoice_number="INV-9001",
        invoice_number_normalized=normalize_invoice_number("INV-9001"),
        invoice_date="2026-01-01", po_number="PO1001", po_number_normalized="PO1001", total_amount=25000,
        document_hash="some-other-hash", decision="APPROVE", reason="test", result_json={},
    )

    dup = check_field_duplicates(vendor, "INV-9001", "2026-01-01", 25000, ledger)
    assert dup.status == "VENDOR_INVOICE_DUPLICATE"


def test_potential_duplicate_same_amount_and_date_different_invoice_number(service):
    from app.duplicate.duplicate_detector import check_field_duplicates
    from app.duplicate.invoice_ledger import InvoiceLedger

    ledger = InvoiceLedger()
    vendor = "Apex Office Supplies Pvt Ltd"
    ledger.insert(
        invoice_id="INV-9002", file_name="prior2.pdf", vendor_name=vendor,
        vendor_name_normalized=normalize_vendor_name(vendor), invoice_number="INV-9002",
        invoice_number_normalized=normalize_invoice_number("INV-9002"),
        invoice_date="2026-01-01", po_number="PO1001", po_number_normalized="PO1001", total_amount=25000,
        document_hash="another-hash", decision="APPROVE", reason="test", result_json={},
    )

    dup = check_field_duplicates(vendor, "INV-DIFFERENT", "2026-01-01", 25000, ledger)
    assert dup.status == "POTENTIAL_DUPLICATE"

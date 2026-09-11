def test_reprocessing_same_invoice_is_rejected_as_duplicate(service, invoice_bytes):
    """PO-scoped duplicate detection: an invoice whose PO number, invoice
    number, and every amount/line-item field match an already-processed
    invoice for that PO is rejected, even though there's no document-hash or
    vendor/invoice-number tracking anymore (see rules/po_invoice_cache.py).
    """
    pdf = invoice_bytes("exact_match.pdf")
    first = service.process_invoice(pdf, "exact_match.pdf")
    assert first.decision != "REJECT"

    second = service.process_invoice(pdf, "exact_match.pdf")
    assert second.decision == "REJECT"
    assert "duplicate invoice for" in second.reason


def test_split_invoice_sequence_is_not_flagged_as_duplicate(service, invoice_bytes):
    """Three legitimate split invoices against the same PO (different
    invoice numbers, different amounts) must NOT be rejected as duplicates.
    """
    r1 = service.process_invoice(invoice_bytes("split_invoice_1.pdf"), "split_invoice_1.pdf")
    r2 = service.process_invoice(invoice_bytes("split_invoice_2.pdf"), "split_invoice_2.pdf")
    r3 = service.process_invoice(invoice_bytes("split_invoice_3.pdf"), "split_invoice_3.pdf")

    assert r1.decision != "REJECT"
    assert r2.decision != "REJECT"
    assert r3.decision != "REJECT"

from app.matching.po_matcher import match_po
from app.models.invoice import InvoiceDetails, InvoiceLineItem, PaymentDetails, StructuredInvoice
from app.models.po import POLineItem, PurchaseOrder

WEIGHTS = {"vendor_match": 30, "item_similarity": 30, "quantity_match": 15, "unit_price_match": 15, "amount_match": 10}


def _po(po_number, vendor, item, qty, price):
    from app.matching.normalization import normalize_po_number, normalize_vendor_name

    return PurchaseOrder(
        po_number=po_number,
        po_number_normalized=normalize_po_number(po_number),
        vendor_name=vendor,
        vendor_name_normalized=normalize_vendor_name(vendor),
        po_amount=round(qty * price, 2),
        line_items=[POLineItem(item_name=item, description=item, quantity=qty, unit_price=price, amount=round(qty * price, 2), spreadsheet_row=2)],
        spreadsheet_row=2,
        all_spreadsheet_rows=[2],
    )


def _invoice(po_number, vendor, item, qty, price):
    return StructuredInvoice(
        invoice_details=InvoiceDetails(vendor_name=vendor, invoice_number="INV-1", invoice_date="2026-01-01", po_number=po_number),
        line_items=[InvoiceLineItem(item_name=item, description=item, quantity=qty, unit_price=price, amount=round(qty * price, 2))],
        payment_details=PaymentDetails(subtotal_amount=round(qty * price, 2), tax_amount=0, total_amount=round(qty * price, 2)),
    )


def test_exact_normalized_po_match():
    pos = [_po("PO1001", "Apex Office Supplies Pvt Ltd", "Paper", 100, 250)]
    invoice = _invoice("PO-1001", "Apex Office Supplies Pvt Ltd", "Paper", 100, 250)
    result = match_po(invoice, pos, threshold=0.85, ambiguous_margin=0.05, level3_weights=WEIGHTS)
    assert result.match_method == "exact_normalized_po"
    assert result.match_confidence == 1.0
    assert result.matched_po.po_number == "PO1001"


def test_partial_malformed_po_match():
    pos = [_po("PO1011", "BrightTech Solutions Pvt Ltd", "USB Hub", 25, 800)]
    invoice = _invoice("Ref: 1011", "BrightTech Solutions Pvt Ltd", "USB Hub", 25, 800)
    result = match_po(invoice, pos, threshold=0.85, ambiguous_margin=0.05, level3_weights=WEIGHTS)
    assert result.match_method == "partial_normalized_po"
    assert result.matched_po.po_number == "PO1011"


def test_missing_po_number_confident_candidate_match():
    pos = [
        _po("PO1004", "Apex Office Supplies Pvt Ltd", "Whiteboard Markers Box", 50, 150),
        _po("PO1001", "Apex Office Supplies Pvt Ltd", "A4 Paper Ream", 100, 250),
    ]
    invoice = _invoice(None, "Apex Office Supplies Pvt Ltd", "Whiteboard Markers Box", 50, 150)
    result = match_po(invoice, pos, threshold=0.85, ambiguous_margin=0.05, level3_weights=WEIGHTS)
    assert result.match_method == "semantic_candidate_match"
    assert result.matched_po.po_number == "PO1004"
    assert result.match_confidence >= 0.85


def test_missing_po_number_ambiguous_when_candidates_are_close():
    pos = [
        _po("PO2001", "Apex Office Supplies Pvt Ltd", "Widget", 10, 100),
        _po("PO2002", "Apex Office Supplies Pvt Ltd", "Widget", 10, 100),
    ]
    invoice = _invoice(None, "Apex Office Supplies Pvt Ltd", "Widget", 10, 100)
    result = match_po(invoice, pos, threshold=0.85, ambiguous_margin=0.05, level3_weights=WEIGHTS)
    assert result.match_method == "ambiguous"
    assert result.matched_po is None


def test_no_confident_match_below_threshold():
    pos = [_po("PO3001", "CloudNine Services Pvt Ltd", "Cloud Storage", 12, 2000)]
    invoice = _invoice(None, "Apex Office Supplies Pvt Ltd", "Completely Different Item", 3, 9)
    result = match_po(invoice, pos, threshold=0.85, ambiguous_margin=0.05, level3_weights=WEIGHTS)
    assert result.match_method == "no_match"
    assert result.matched_po is None

from app.duplicate.invoice_ledger import InvoiceLedger
from app.rules.split_invoice import evaluate_split_invoice


def test_split_invoice_cumulative_math(settings):
    from app.database import init_db

    init_db()
    ledger = InvoiceLedger()

    info1 = evaluate_split_invoice(
        po_number_normalized="PO1010",
        vendor_name_normalized="deltafacilitiesmanagement",
        current_invoice_total=40000,
        po_amount=100000,
        tolerance_type="absolute",
        tolerance_value=500,
        ledger=ledger,
    )
    assert info1.invoice_type == "PARTIAL_INVOICE"
    assert info1.previously_invoiced == 0
    assert info1.cumulative_invoiced == 40000
    assert info1.remaining_balance == 60000

    ledger.insert(
        invoice_id="INV-A", file_name="a.pdf", vendor_name="Delta Facilities Management",
        vendor_name_normalized="deltafacilitiesmanagement", invoice_number="INV-A", invoice_number_normalized="INVA",
        invoice_date="2026-02-01", po_number="PO1010", po_number_normalized="PO1010", total_amount=40000,
        document_hash="hash-a", decision="APPROVE_PARTIAL", reason="test", result_json={},
    )

    info2 = evaluate_split_invoice(
        po_number_normalized="PO1010",
        vendor_name_normalized="deltafacilitiesmanagement",
        current_invoice_total=60000,
        po_amount=100000,
        tolerance_type="absolute",
        tolerance_value=500,
        ledger=ledger,
    )
    assert info2.previously_invoiced == 40000
    assert info2.cumulative_invoiced == 100000
    assert info2.remaining_balance == 0
    assert info2.invoice_type == "PARTIAL_INVOICE"  # part of a multi-invoice sequence


def test_full_invoice_not_marked_partial(settings):
    from app.database import init_db

    init_db()
    ledger = InvoiceLedger()
    info = evaluate_split_invoice(
        po_number_normalized="PO1001",
        vendor_name_normalized="apexofficesuppliespvtltd",
        current_invoice_total=25000,
        po_amount=25000,
        tolerance_type="percentage",
        tolerance_value=1,
        ledger=ledger,
    )
    assert info.invoice_type == "FULL_INVOICE"

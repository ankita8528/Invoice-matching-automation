from app.rules.po_invoice_cache import POInvoiceCache
from app.rules.split_invoice import evaluate_split_invoice


def _insert(cache, po, invnum, subtotal, decision):
    cache.insert(
        po_number_normalized=po,
        invoice_number_normalized=invnum,
        subtotal_amount=subtotal,
        tax_amount=0,
        total_amount=subtotal,
        line_items=[],
        decision=decision,
    )


def test_split_invoice_cumulative_math(settings):
    from app.database import init_db

    init_db()
    cache = POInvoiceCache()

    info1 = evaluate_split_invoice(
        po_number_normalized="PO1010",
        current_invoice_total=40000,
        po_amount=100000,
        tolerance_type="absolute",
        tolerance_value=500,
        cache=cache,
    )
    assert info1.invoice_type == "PARTIAL_INVOICE"
    assert info1.previously_invoiced == 0
    assert info1.cumulative_invoiced == 40000
    assert info1.remaining_balance == 60000

    _insert(cache, "PO1010", "INV-A", 40000, "Accept/partial payment")

    info2 = evaluate_split_invoice(
        po_number_normalized="PO1010",
        current_invoice_total=60000,
        po_amount=100000,
        tolerance_type="absolute",
        tolerance_value=500,
        cache=cache,
    )
    assert info2.previously_invoiced == 40000
    assert info2.cumulative_invoiced == 100000
    assert info2.remaining_balance == 0
    assert info2.invoice_type == "PARTIAL_INVOICE"  # part of a multi-invoice sequence


def test_full_invoice_not_marked_partial(settings):
    from app.database import init_db

    init_db()
    cache = POInvoiceCache()
    info = evaluate_split_invoice(
        po_number_normalized="PO1001",
        current_invoice_total=25000,
        po_amount=25000,
        tolerance_type="percentage",
        tolerance_value=1,
        cache=cache,
    )
    assert info.invoice_type == "FULL_INVOICE"


def test_only_approved_decisions_count_toward_cumulative(settings):
    """A REVIEW/REJECT row must not contribute to the cumulative total --
    only APPROVE/Accept-partial-payment amounts represent actually-accepted invoicing.
    """
    from app.database import init_db

    init_db()
    cache = POInvoiceCache()
    _insert(cache, "PO2010", "INV-B", 40000, "REVIEW")
    _insert(cache, "PO2010", "INV-C", 99999, "REJECT")

    info = evaluate_split_invoice(
        po_number_normalized="PO2010",
        current_invoice_total=30000,
        po_amount=100000,
        tolerance_type="absolute",
        tolerance_value=500,
        cache=cache,
    )
    assert info.previously_invoiced == 0
    assert info.cumulative_invoiced == 30000

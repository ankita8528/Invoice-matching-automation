from app.models.invoice import InvoiceLineItem
from app.rules.po_invoice_cache import POInvoiceCache


def _line_items():
    return [InvoiceLineItem(item_name="Widget", description="Widget", quantity=10, unit_price=100, amount=1000)]


def test_find_duplicate_matches_identical_invoice(settings):
    from app.database import init_db

    init_db()
    cache = POInvoiceCache()
    cache.insert(
        po_number_normalized="PO1001",
        invoice_number_normalized="INV1",
        subtotal_amount=1000,
        tax_amount=0,
        total_amount=1000,
        line_items=_line_items(),
        decision="APPROVE",
    )

    match = cache.find_duplicate(
        po_number_normalized="PO1001",
        invoice_number_normalized="INV1",
        subtotal_amount=1000,
        tax_amount=0,
        total_amount=1000,
        line_items=_line_items(),
    )
    assert match is not None
    assert match.po_number_normalized == "PO1001"


def test_find_duplicate_none_when_invoice_number_differs(settings):
    from app.database import init_db

    init_db()
    cache = POInvoiceCache()
    cache.insert(
        po_number_normalized="PO1001",
        invoice_number_normalized="INV1",
        subtotal_amount=1000,
        tax_amount=0,
        total_amount=1000,
        line_items=_line_items(),
        decision="APPROVE",
    )

    match = cache.find_duplicate(
        po_number_normalized="PO1001",
        invoice_number_normalized="INV2",  # different invoice number -- legitimate resubmission/split
        subtotal_amount=1000,
        tax_amount=0,
        total_amount=1000,
        line_items=_line_items(),
    )
    assert match is None


def test_find_duplicate_none_when_amount_differs(settings):
    from app.database import init_db

    init_db()
    cache = POInvoiceCache()
    cache.insert(
        po_number_normalized="PO1001",
        invoice_number_normalized="INV1",
        subtotal_amount=1000,
        tax_amount=0,
        total_amount=1000,
        line_items=_line_items(),
        decision="APPROVE",
    )

    match = cache.find_duplicate(
        po_number_normalized="PO1001",
        invoice_number_normalized="INV1",
        subtotal_amount=2000,  # different amount -- not a duplicate
        tax_amount=0,
        total_amount=2000,
        line_items=_line_items(),
    )
    assert match is None


def test_find_duplicate_none_when_line_items_differ(settings):
    from app.database import init_db

    init_db()
    cache = POInvoiceCache()
    cache.insert(
        po_number_normalized="PO1001",
        invoice_number_normalized="INV1",
        subtotal_amount=1000,
        tax_amount=0,
        total_amount=1000,
        line_items=_line_items(),
        decision="APPROVE",
    )

    different_items = [InvoiceLineItem(item_name="Gadget", description="Gadget", quantity=10, unit_price=100, amount=1000)]
    match = cache.find_duplicate(
        po_number_normalized="PO1001",
        invoice_number_normalized="INV1",
        subtotal_amount=1000,
        tax_amount=0,
        total_amount=1000,
        line_items=different_items,
    )
    assert match is None

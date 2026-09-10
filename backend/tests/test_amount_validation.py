from app.models.invoice import InvoiceDetails, InvoiceLineItem, PaymentDetails, StructuredInvoice
from app.rules.tolerance import check_tolerance
from app.validation.amount_validator import validate_arithmetic


def _invoice(subtotal, tax, total, items):
    return StructuredInvoice(
        invoice_details=InvoiceDetails(),
        line_items=[InvoiceLineItem(item_name="x", description="x", quantity=q, unit_price=p, amount=a) for q, p, a in items],
        payment_details=PaymentDetails(subtotal_amount=subtotal, tax_amount=tax, total_amount=total),
    )


def test_arithmetic_passes_when_consistent():
    invoice = _invoice(25000, 0, 25000, [(100, 250, 25000)])
    result = validate_arithmetic(invoice, epsilon=1.0)
    assert result.status == "PASS"


def test_arithmetic_fails_on_total_mismatch():
    invoice = _invoice(48000, 4800, 50000, [(40, 1200, 48000)])
    result = validate_arithmetic(invoice, epsilon=1.0)
    assert result.status == "FAIL"


def test_arithmetic_fails_on_line_item_mismatch():
    invoice = _invoice(25000, 0, 25000, [(100, 250, 20000)])  # 100*250=25000 != stated 20000
    result = validate_arithmetic(invoice, epsilon=1.0)
    assert result.status == "FAIL"


def test_percentage_tolerance_within():
    r = check_tolerance(invoice_amount=25100, reference_amount=25000, tolerance_type="percentage", tolerance_value=1)
    assert r.within_tolerance is True
    assert r.allowed_difference == 250.0


def test_percentage_tolerance_exceeded():
    r = check_tolerance(invoice_amount=26000, reference_amount=25000, tolerance_type="percentage", tolerance_value=1)
    assert r.within_tolerance is False


def test_absolute_tolerance_within():
    r = check_tolerance(invoice_amount=65400, reference_amount=65000, tolerance_type="absolute", tolerance_value=500)
    assert r.within_tolerance is True


def test_absolute_tolerance_exceeded():
    r = check_tolerance(invoice_amount=65600, reference_amount=65000, tolerance_type="absolute", tolerance_value=500)
    assert r.within_tolerance is False

from app.matching.normalization import normalize_invoice_number, normalize_po_number, normalize_vendor_name


def test_po_number_normalization_equivalence():
    variants = ["PO1005", "PO-1005", "PO 1005", "po-1005", "PO/1005"]
    normalized = {normalize_po_number(v) for v in variants}
    assert normalized == {"PO1005"}


def test_po_number_normalization_empty():
    assert normalize_po_number(None) == ""
    assert normalize_po_number("") == ""


def test_vendor_name_normalization_suffix_variants():
    a = normalize_vendor_name("Apex Office Supplies Pvt Ltd")
    b = normalize_vendor_name("Apex Office Supplies Private Limited")
    c = normalize_vendor_name("apex office supplies, pvt. ltd.")
    assert a == b == c


def test_vendor_name_normalization_distinguishes_different_vendors():
    assert normalize_vendor_name("Apex Office Supplies Pvt Ltd") != normalize_vendor_name("BrightTech Solutions Pvt Ltd")


def test_invoice_number_normalization():
    assert normalize_invoice_number("INV-2001") == normalize_invoice_number("inv 2001")

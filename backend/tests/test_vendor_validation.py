from app.validation.vendor_validator import VendorRecord, validate_vendor
from app.matching.normalization import normalize_vendor_name

VENDORS = [
    VendorRecord("V001", "Apex Office Supplies Pvt Ltd", normalize_vendor_name("Apex Office Supplies Pvt Ltd"), "APPROVED", "percentage", 1),
    VendorRecord("V005", "Unknown Vendor", normalize_vendor_name("Unknown Vendor"), "NOT_APPROVED", "percentage", 0),
]


def test_approved_vendor_exact_match():
    check, info = validate_vendor("Apex Office Supplies Pvt Ltd", VENDORS)
    assert check.status == "PASS"
    assert info.status == "APPROVED"
    assert info.match_confidence == 1.0


def test_vendor_name_variant_still_matches():
    check, info = validate_vendor("Apex Office Supplies Private Limited", VENDORS)
    assert info.status == "APPROVED"
    assert info.match_confidence == 1.0  # normalization makes this an exact match


def test_not_approved_vendor_fails():
    check, info = validate_vendor("Unknown Vendor", VENDORS)
    assert check.status == "FAIL"
    assert info.status == "NOT_APPROVED"


def test_unknown_vendor_not_in_master():
    check, info = validate_vendor("Some Random Vendor Ltd", VENDORS)
    assert check.status == "FAIL"
    assert info.status == "UNKNOWN"

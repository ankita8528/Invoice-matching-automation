# Invoice + PO Matching Test Dataset

This dataset is designed to test an invoice-processing / PO-matching pipeline with both digital PDFs and image-based scanned PDFs.

## Contents
- `invoices/` — 12 invoice PDFs: 6 digital and 6 scanned/image-based.
- `PO_match_dataset.xlsx` — purchase orders, invoice ground truth, vendor master, matching rules, candidate matches, and expected processing log.

## Edge cases covered
1. Clean digital exact match
2. Scanned exact match
3. Unit-price mismatch
4. Quantity mismatch
5. Missing PO reference
6. Tax/total arithmetic inconsistency
7. Missing invoice date
8. Wrong line item against the referenced PO
9. Separate tax with correct arithmetic
10. Vendor not approved
11. Different invoice layouts / labels
12. Statement-style invoice rather than standard invoice

## Expected decisions
- APPROVE: exact/valid matches where required checks pass.
- REVIEW: missing information, mismatches, or arithmetic exceptions requiring human judgment.
- REJECT: unapproved vendor in this dataset.

## Important implementation note
The workbook's `purchase_orders` sheet is the source of PO truth. `invoice_ground_truth` is test metadata/expected output, not an input your production matcher would normally receive. The `candidate_matches` sheet is included to demonstrate how a missing-PO case can be evaluated without silently assuming a PO.

All invoice PDFs in `invoices/` are copies of the provided/generated source invoices; their contents have not been silently corrected.

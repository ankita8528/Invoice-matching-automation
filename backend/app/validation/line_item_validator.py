"""Deterministic invoice <-> PO line-item comparison.

Produces the quantity_match / unit_price_match / line_item_match checks.
Amount/tolerance-level total comparisons live in rules/tolerance.py; this
module only compares line-item-level detail.
"""
from __future__ import annotations

from app.matching.fuzzy_matcher import numeric_closeness, text_similarity
from app.models.invoice import StructuredInvoice
from app.models.po import PurchaseOrder
from app.models.result import CheckResult, CheckStatus

# Line items are considered "the same item" for comparison purposes above this
# text-similarity score.
ITEM_MATCH_FLOOR = 0.55
# Below this closeness score a quantity/price is considered a real mismatch
# rather than noise from rounding/bundling.
NUMERIC_MATCH_FLOOR = 0.98


def compare_line_items(invoice: StructuredInvoice, po: PurchaseOrder) -> tuple[CheckResult, CheckResult, CheckResult]:
    """Returns (line_item_match, quantity_match, unit_price_match)."""
    if not invoice.line_items or not po.line_items:
        warn = CheckResult(status=CheckStatus.WARNING, reason="No line items available on one side to compare.")
        return warn, warn, warn

    # Match each invoice line item to its best PO line item (greedy by similarity).
    pairs: list[tuple] = []
    used_po_idx: set[int] = set()
    for inv_item in invoice.line_items:
        inv_text = inv_item.description or inv_item.item_name
        best_idx, best_score = None, 0.0
        for idx, po_item in enumerate(po.line_items):
            if idx in used_po_idx:
                continue
            po_text = po_item.description or po_item.item_name
            score = text_similarity(inv_text, po_text)
            if score > best_score:
                best_idx, best_score = idx, score
        if best_idx is not None:
            used_po_idx.add(best_idx)
            pairs.append((inv_item, po.line_items[best_idx], best_score))
        else:
            pairs.append((inv_item, None, 0.0))

    unmatched = [p for p in pairs if p[1] is None or p[2] < ITEM_MATCH_FLOOR]
    inv_total_qty = sum(li.quantity or 0 for li in invoice.line_items)
    po_total_qty = sum(li.quantity or 0 for li in po.line_items)

    inv_prices = [li.unit_price for li in invoice.line_items if li.unit_price is not None]
    po_prices = [li.unit_price for li in po.line_items if li.unit_price is not None]
    price_closeness = 1.0
    price_diffs: list[str] = []
    if inv_prices and po_prices:
        for inv_item, po_item, score in pairs:
            if po_item is None or inv_item.unit_price is None or po_item.unit_price is None:
                continue
            c = numeric_closeness(inv_item.unit_price, po_item.unit_price)
            price_closeness = min(price_closeness, c)
            if c < NUMERIC_MATCH_FLOOR:
                price_diffs.append(
                    f"'{inv_item.description or inv_item.item_name}': invoice unit_price {inv_item.unit_price} vs PO {po_item.unit_price}"
                )

    if unmatched and len(unmatched) == len(pairs):
        line_item_result = CheckResult(
            status=CheckStatus.FAIL,
            reason="No invoice line items could be matched to any PO line item.",
        )
    elif unmatched:
        line_item_result = CheckResult(
            status=CheckStatus.WARNING,
            reason=f"{len(unmatched)} of {len(pairs)} invoice line item(s) did not clearly match a PO line item "
            "(may be bundled/split differently); totals are still reconciled separately.",
        )
    else:
        line_item_result = CheckResult(status=CheckStatus.PASS, reason="All invoice line items matched corresponding PO line items.")

    # Quantity check only flags OVERBILLING (invoicing more units than the PO
    # allows). Invoicing fewer units than the PO is a normal, legitimate
    # partial/split invoice (see rules/split_invoice.py) and must not fail here.
    overbilled = inv_total_qty > po_total_qty * 1.02 + 1e-6
    if not overbilled:
        qty_result = CheckResult(
            status=CheckStatus.PASS,
            expected=po_total_qty,
            actual=inv_total_qty,
            difference=round(inv_total_qty - po_total_qty, 4),
            reason="Invoice quantity is within (or a legitimate partial subset of) the PO quantity.",
        )
    else:
        qty_result = CheckResult(
            status=CheckStatus.FAIL,
            expected=po_total_qty,
            actual=inv_total_qty,
            difference=round(inv_total_qty - po_total_qty, 4),
            reason=f"Invoice total quantity {inv_total_qty} exceeds PO total quantity {po_total_qty} (overbilling).",
        )

    if not inv_prices or not po_prices:
        price_result = CheckResult(status=CheckStatus.NOT_CHECKED, reason="Unit price not available on one side.")
    elif price_closeness >= NUMERIC_MATCH_FLOOR:
        price_result = CheckResult(status=CheckStatus.PASS, reason="Unit prices match PO within noise tolerance.")
    else:
        price_result = CheckResult(status=CheckStatus.FAIL, reason="Unit price mismatch: " + "; ".join(price_diffs))

    return line_item_result, qty_result, price_result

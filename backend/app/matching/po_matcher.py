"""PO matching hierarchy (see README for the full design rationale).

LEVEL 1 - exact normalized PO number match.
LEVEL 2 - partial/malformed PO number, deterministic normalization + containment.
LEVEL 3 - no usable PO number: weighted candidate scoring against vendor +
          line items + quantities + prices + amount. Returns *ranked
          candidates*; the caller (processing_service) decides whether the
          top candidate is confident enough and unambiguous enough to use.

This module NEVER makes the final accept/reject call by itself -- it only
produces a match (or a ranked candidate list) plus a numeric confidence.
The decision engine is the only place that turns confidence into REVIEW.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from app.matching.fuzzy_matcher import numeric_closeness, text_similarity, vendor_similarity
from app.matching.normalization import normalize_po_number
from app.models.invoice import StructuredInvoice
from app.models.po import PurchaseOrder
from app.models.result import POCandidate


@dataclass
class MatchResult:
    matched_po: PurchaseOrder | None
    match_method: str  # exact_normalized_po | partial_normalized_po | semantic_candidate_match | ambiguous | no_match
    match_confidence: float
    candidates: list[POCandidate] = field(default_factory=list)
    reason: str = ""


def _invoice_amount(invoice: StructuredInvoice) -> float | None:
    return invoice.payment_details.total_amount


def _level3_score(invoice: StructuredInvoice, po: PurchaseOrder, weights: dict) -> tuple[float, list[str]]:
    reasons: list[str] = []

    v_score = vendor_similarity(invoice.invoice_details.vendor_name, po.vendor_name)
    reasons.append(f"vendor_similarity={v_score:.2f}")

    # Item similarity: best match between any invoice line item and any PO line item.
    item_score = 0.0
    if invoice.line_items and po.line_items:
        best = 0.0
        for inv_item in invoice.line_items:
            inv_text = inv_item.description or inv_item.item_name
            for po_item in po.line_items:
                po_text = po_item.description or po_item.item_name
                best = max(best, text_similarity(inv_text, po_text))
        item_score = best
    reasons.append(f"item_similarity={item_score:.2f}")

    qty_score = 0.0
    price_score = 0.0
    if invoice.line_items and po.line_items:
        inv_qty_total = sum(li.quantity or 0 for li in invoice.line_items)
        po_qty_total = sum(li.quantity or 0 for li in po.line_items)
        qty_score = numeric_closeness(inv_qty_total, po_qty_total)

        inv_prices = [li.unit_price for li in invoice.line_items if li.unit_price is not None]
        po_prices = [li.unit_price for li in po.line_items if li.unit_price is not None]
        if inv_prices and po_prices:
            price_score = numeric_closeness(sum(inv_prices) / len(inv_prices), sum(po_prices) / len(po_prices))
    reasons.append(f"quantity_match={qty_score:.2f}")
    reasons.append(f"unit_price_match={price_score:.2f}")

    amount_score = numeric_closeness(_invoice_amount(invoice), po.po_amount)
    reasons.append(f"amount_match={amount_score:.2f}")

    total_weight = sum(weights.values())
    weighted = (
        v_score * weights["vendor_match"]
        + item_score * weights["item_similarity"]
        + qty_score * weights["quantity_match"]
        + price_score * weights["unit_price_match"]
        + amount_score * weights["amount_match"]
    ) / total_weight

    return weighted, reasons


def match_po(
    invoice: StructuredInvoice,
    purchase_orders: list[PurchaseOrder],
    *,
    threshold: float,
    ambiguous_margin: float,
    level3_weights: dict,
) -> MatchResult:
    raw_po_number = invoice.invoice_details.po_number
    normalized_invoice_po = normalize_po_number(raw_po_number)

    if normalized_invoice_po:
        # LEVEL 1: exact normalized match.
        exact_matches = [po for po in purchase_orders if po.po_number_normalized == normalized_invoice_po]
        if len(exact_matches) == 1:
            return MatchResult(
                matched_po=exact_matches[0],
                match_method="exact_normalized_po",
                match_confidence=1.0,
                reason=f"Invoice PO reference '{raw_po_number}' normalized to "
                f"'{normalized_invoice_po}' matched PO {exact_matches[0].po_number} exactly.",
            )
        if len(exact_matches) > 1:
            # Should not happen with well-formed PO data, but never silently pick one.
            candidates = [POCandidate(po_number=po.po_number, score=1.0, reasons=["exact_normalized_po"]) for po in exact_matches]
            return MatchResult(
                matched_po=None,
                match_method="ambiguous",
                match_confidence=1.0,
                candidates=candidates,
                reason=f"Multiple PO rows share normalized PO number '{normalized_invoice_po}'.",
            )

        # LEVEL 2: partial/malformed PO number. Try digits-only containment
        # (e.g. invoice says "Ref: 1005" and PO is "PO1005"), and small edit
        # distance on the normalized strings.
        digits_only = "".join(ch for ch in normalized_invoice_po if ch.isdigit())
        partial_candidates: list[tuple[PurchaseOrder, float, str]] = []
        for po in purchase_orders:
            po_digits = "".join(ch for ch in po.po_number_normalized if ch.isdigit())
            if digits_only and po_digits and digits_only == po_digits:
                partial_candidates.append((po, 0.9, "digits_only_match"))
                continue
            if digits_only and po_digits and (digits_only in po_digits or po_digits in digits_only) and len(digits_only) >= 3:
                partial_candidates.append((po, 0.75, "digits_containment"))

        if partial_candidates:
            partial_candidates.sort(key=lambda t: t[1], reverse=True)
            best_po, best_score, best_reason = partial_candidates[0]
            others_same_score = [p for p in partial_candidates[1:] if abs(p[1] - best_score) < 1e-9]
            if others_same_score:
                candidates = [
                    POCandidate(po_number=p.po_number, score=s, reasons=[r]) for p, s, r in partial_candidates
                ]
                return MatchResult(
                    matched_po=None,
                    match_method="ambiguous",
                    match_confidence=best_score,
                    candidates=candidates,
                    reason=f"PO reference '{raw_po_number}' partially matches multiple POs.",
                )
            return MatchResult(
                matched_po=best_po,
                match_method="partial_normalized_po",
                match_confidence=best_score,
                candidates=[POCandidate(po_number=best_po.po_number, score=best_score, reasons=[best_reason])],
                reason=f"PO reference '{raw_po_number}' matched PO {best_po.po_number} via malformed-reference normalization ({best_reason}).",
            )
        # Fall through to level 3 if the malformed PO number matched nothing.

    # LEVEL 3: no usable PO number (or level 1/2 found nothing) -> candidate scoring.
    scored: list[tuple[PurchaseOrder, float, list[str]]] = []
    for po in purchase_orders:
        score, reasons = _level3_score(invoice, po, level3_weights)
        scored.append((po, score, reasons))
    scored.sort(key=lambda t: t[1], reverse=True)

    candidates = [POCandidate(po_number=po.po_number, score=round(score, 4), reasons=reasons) for po, score, reasons in scored[:5]]

    if not scored:
        return MatchResult(matched_po=None, match_method="no_match", match_confidence=0.0, reason="No purchase orders available to match against.")

    top_po, top_score, top_reasons = scored[0]
    second_score = scored[1][1] if len(scored) > 1 else 0.0

    if top_score < threshold:
        return MatchResult(
            matched_po=None,
            match_method="no_match",
            match_confidence=top_score,
            candidates=candidates,
            reason=f"Best PO candidate ({top_po.po_number}) scored {top_score:.2f}, below the confidence threshold {threshold:.2f}.",
        )

    if (top_score - second_score) < ambiguous_margin:
        return MatchResult(
            matched_po=None,
            match_method="ambiguous",
            match_confidence=top_score,
            candidates=candidates,
            reason=f"Top two PO candidates are within {ambiguous_margin:.2f} of each other ({top_score:.2f} vs {second_score:.2f}); cannot confidently disambiguate.",
        )

    return MatchResult(
        matched_po=top_po,
        match_method="semantic_candidate_match",
        match_confidence=top_score,
        candidates=candidates,
        reason=f"No usable PO number on the invoice; matched PO {top_po.po_number} via vendor/line-item/amount similarity (score {top_score:.2f}).",
    )

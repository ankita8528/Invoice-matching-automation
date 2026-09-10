"""The end-to-end pipeline orchestrator.

This is the only module that calls every other layer in sequence. It is
intentionally NOT an autonomous agent: every step below is a plain Python
function call in a fixed order (see README architecture diagram). The
optional exception agent (agent/exception_agent.py) is invoked, if enabled,
only *after* the deterministic decision has already been made, and it can
never change that decision.
"""
from __future__ import annotations

import hashlib
import logging
import time

from app.agent.exception_agent import build_context_summary, investigate
from app.config import Settings
from app.duplicate.duplicate_detector import check_exact_document_duplicate, check_field_duplicates
from app.duplicate.invoice_ledger import InvoiceLedger
from app.extraction.invoice_parser import normalize_vision_json, parse_digital_text
from app.extraction.ocr import OCRUnavailableError, configure_tesseract, run_ocr
from app.extraction.pdf_extractor import InvalidPDFError, extract_text, render_first_page_to_image
from app.extraction.vision_extractor import VisionExtractionError, extract_structured_json
from app.matching.fuzzy_matcher import vendor_similarity
from app.matching.normalization import normalize_invoice_number, normalize_po_number, normalize_vendor_name
from app.matching.po_matcher import MatchResult, match_po
from app.models.invoice import StructuredInvoice
from app.models.result import (
    AmountAnalysis,
    AuditTrail,
    CheckResult,
    CheckStatus,
    Decision,
    DecisionResult,
    DuplicateInfo,
    MatchedPO,
    POCandidate,
    SplitInvoiceInfo,
    VendorInfo,
)
from app.rules.decision_engine import decide
from app.rules.split_invoice import evaluate_split_invoice
from app.rules.tolerance import check_tolerance
from app.services.data_loader import DataStore
from app.validation.amount_validator import validate_arithmetic
from app.validation.invoice_validator import validate_required_fields
from app.validation.line_item_validator import compare_line_items
from app.validation.vendor_validator import validate_vendor

logger = logging.getLogger("app.processing")

VENDOR_IDENTITY_CONFLICT_FLOOR = 0.3


def _extraction_check(invoice: StructuredInvoice) -> CheckResult:
    confidence = invoice.extraction_metadata.confidence or 0.0
    method = invoice.extraction_metadata.method
    if confidence >= 0.8:
        return CheckResult(status=CheckStatus.PASS, reason=f"Extraction ({method}) succeeded with confidence {confidence:.2f}.")
    if confidence >= 0.4:
        return CheckResult(status=CheckStatus.WARNING, reason=f"Extraction ({method}) succeeded but with low confidence ({confidence:.2f}); several fields may be missing.")
    return CheckResult(status=CheckStatus.FAIL, reason=f"Extraction ({method}) has very low confidence ({confidence:.2f}); most fields could not be read.")


def _empty_structured_result(reason: str, document_hash: str, method: str, steps: list[str]) -> DecisionResult:
    return DecisionResult(
        decision=Decision.REVIEW,
        reason=reason,
        checks={"invoice_extraction": CheckResult(status=CheckStatus.FAIL, reason=reason)},
        invoice_extraction=None,
        audit=AuditTrail(processing_steps=steps, document_hash=document_hash, extraction_method=method),
    )


class ProcessingService:
    def __init__(self, settings: Settings, data_store: DataStore, ledger: InvoiceLedger):
        self.settings = settings
        self.data_store = data_store
        self.ledger = ledger
        configure_tesseract(settings.tesseract_cmd)

    def process_invoice(self, pdf_bytes: bytes, file_name: str) -> DecisionResult:
        steps: list[str] = [f"Invoice received: {file_name}"]
        document_hash = hashlib.sha256(pdf_bytes).hexdigest()
        steps.append(f"SHA256 calculated: {document_hash}")

        # --- Duplicate detection happens BEFORE any expensive extraction ---
        exact_dup = check_exact_document_duplicate(document_hash, self.ledger)
        if exact_dup.status == "EXACT_DUPLICATE":
            steps.append(f"Exact document duplicate detected: {exact_dup.reason}")
            result = DecisionResult(
                decision=Decision.REJECT,
                reason=exact_dup.reason,
                checks={"duplicate_check": CheckResult(status=CheckStatus.FAIL, reason=exact_dup.reason)},
                duplicate=exact_dup,
                audit=AuditTrail(processing_steps=steps, document_hash=document_hash),
            )
            self._persist(
                invoice_id=f"HASH-{document_hash[:12]}",
                file_name=file_name,
                vendor_name="",
                invoice_number="",
                invoice_date=None,
                po_number=None,
                total_amount=None,
                document_hash=document_hash,
                result=result,
            )
            return result
        steps.append("Duplicate check (exact document) passed: no identical document on file.")

        # --- Text extraction ---
        try:
            extracted = extract_text(pdf_bytes, min_length_for_digital=self.settings.min_text_length_for_digital)
        except InvalidPDFError as exc:
            reason = f"Invoice could not be reliably extracted: {exc}"
            steps.append(reason)
            result = _empty_structured_result(reason, document_hash, "none", steps)
            self._persist(f"HASH-{document_hash[:12]}", file_name, "", "", None, None, None, document_hash, result)
            return result

        if extracted.is_meaningful:
            steps.append("Digital PDF detected (usable text layer found).")
            invoice = parse_digital_text(extracted.text)
            steps.append("Invoice fields extracted via PyMuPDF text parsing.")
        else:
            steps.append("PDF text extraction returned no usable text.")
            steps.append("Scanned/image PDF detected.")
            try:
                image = render_first_page_to_image(pdf_bytes)
                steps.append("PDF rendered to image.")
            except InvalidPDFError as exc:
                reason = f"Invoice could not be reliably extracted: {exc}"
                steps.append(reason)
                result = _empty_structured_result(reason, document_hash, "none", steps)
                self._persist(f"HASH-{document_hash[:12]}", file_name, "", "", None, None, None, document_hash, result)
                return result

            ocr_text = ""
            try:
                ocr_text = run_ocr(image)
                steps.append("Tesseract OCR executed.")
            except OCRUnavailableError as exc:
                steps.append(f"Tesseract OCR unavailable ({exc}); continuing with vision model on image alone.")

            try:
                raw_json = extract_structured_json(
                    image,
                    ocr_text,
                    provider=self.settings.vision_provider,
                    model=self.settings.qwen_model,
                    base_url=self.settings.ollama_base_url,
                    timeout_seconds=self.settings.vision_request_timeout_seconds,
                )
                invoice = normalize_vision_json(raw_json)
                steps.append("Qwen3-VL extraction executed.")
                steps.append("Structured invoice JSON created.")
            except VisionExtractionError as exc:
                reason = f"Invoice could not be reliably extracted: {exc}"
                steps.append(reason)
                result = _empty_structured_result(reason, document_hash, "tesseract_qwen3_vl", steps)
                self._persist(f"HASH-{document_hash[:12]}", file_name, "", "", None, None, None, document_hash, result)
                return result

        d = invoice.invoice_details
        p = invoice.payment_details
        vendor_norm = normalize_vendor_name(d.vendor_name)
        invnum_norm = normalize_invoice_number(d.invoice_number)

        checks: dict[str, CheckResult] = {}
        checks["invoice_extraction"] = _extraction_check(invoice)
        checks["required_fields_present"] = validate_required_fields(invoice)
        checks["arithmetic_check"] = validate_arithmetic(invoice, epsilon=self.settings.arithmetic_tolerance)
        steps.append("Invoice arithmetic validated.")

        # --- Field-level duplicate checks (vendor+invoice number, potential dup) ---
        duplicate = check_field_duplicates(d.vendor_name, d.invoice_number, d.invoice_date, p.total_amount, self.ledger)
        checks["duplicate_check"] = (
            CheckResult(status=CheckStatus.PASS, reason="No duplicate signals found.")
            if duplicate.status == "NONE"
            else CheckResult(status=CheckStatus.FAIL if duplicate.status == "VENDOR_INVOICE_DUPLICATE" else CheckStatus.WARNING, reason=duplicate.reason)
        )
        steps.append(f"Duplicate check (vendor/invoice number): {duplicate.status}")

        # --- Vendor validation ---
        vendor_check, vendor_info = validate_vendor(d.vendor_name, self.data_store.get_vendors())
        checks["vendor_approved"] = vendor_check
        steps.append(f"Vendor validated: {vendor_info.status} (confidence {vendor_info.match_confidence:.2f}).")

        # --- PO matching ---
        steps.append(f"PO reference normalized: '{d.po_number}' -> '{normalize_po_number(d.po_number)}'." if d.po_number else "No PO number present on invoice.")
        match_result: MatchResult = match_po(
            invoice,
            self.data_store.get_purchase_orders(),
            threshold=self.settings.po_match_threshold,
            ambiguous_margin=self.settings.ambiguous_match_margin,
            level3_weights={
                "vendor_match": self.settings.level3_weight_vendor,
                "item_similarity": self.settings.level3_weight_item,
                "quantity_match": self.settings.level3_weight_quantity,
                "unit_price_match": self.settings.level3_weight_unit_price,
                "amount_match": self.settings.level3_weight_amount,
            },
        )
        steps.append(match_result.reason)

        matched_po_model: MatchedPO | None = None
        amount_analysis: AmountAnalysis
        split_info = SplitInvoiceInfo(invoice_type="FULL_INVOICE")

        if match_result.matched_po is not None:
            po = match_result.matched_po
            checks["po_number_match"] = (
                CheckResult(status=CheckStatus.PASS, reason=f"PO number matched via {match_result.match_method}.")
                if match_result.match_method in ("exact_normalized_po", "partial_normalized_po")
                else CheckResult(status=CheckStatus.NOT_CHECKED, reason="No PO number on invoice; matched via candidate scoring instead.")
            )
            checks["po_match"] = CheckResult(status=CheckStatus.PASS, expected=po.po_number, actual=po.po_number, reason=match_result.reason)

            identity_score = vendor_similarity(d.vendor_name, po.vendor_name)
            if identity_score < VENDOR_IDENTITY_CONFLICT_FLOOR:
                checks["vendor_po_identity_conflict"] = CheckResult(
                    status=CheckStatus.FAIL,
                    expected=po.vendor_name,
                    actual=d.vendor_name,
                    reason=f"Invoice vendor '{d.vendor_name}' does not match matched PO {po.po_number}'s vendor "
                    f"'{po.vendor_name}' (similarity {identity_score:.2f}); possible misdirected or fraudulent invoice.",
                )
            else:
                checks["vendor_po_identity_conflict"] = CheckResult(status=CheckStatus.PASS, reason="Invoice vendor matches PO vendor identity.")

            line_item_match, quantity_match, unit_price_match = compare_line_items(invoice, po)
            checks["line_item_match"] = line_item_match
            checks["quantity_match"] = quantity_match
            checks["unit_price_match"] = unit_price_match
            steps.append("Line items compared against matched PO.")

            # A PO-level tolerance override (if the PO spreadsheet specifies one)
            # takes precedence over the vendor's default tolerance.
            if po.tolerance_value is not None:
                tolerance_type = po.tolerance_type or "percentage"
                tolerance_value = po.tolerance_value
            else:
                tolerance_type = vendor_info.tolerance_type or "percentage"
                tolerance_value = vendor_info.tolerance_value if vendor_info.tolerance_value is not None else 0.0

            split_info = evaluate_split_invoice(
                po_number_normalized=po.po_number_normalized,
                vendor_name_normalized=vendor_norm,
                current_invoice_total=p.total_amount,
                po_amount=po.po_amount,
                tolerance_type=tolerance_type,
                tolerance_value=tolerance_value,
                ledger=self.ledger,
            )
            steps.append(
                f"Split-invoice check: type={split_info.invoice_type}, previously_invoiced={split_info.previously_invoiced}, "
                f"cumulative_invoiced={split_info.cumulative_invoiced}, remaining_balance={split_info.remaining_balance}."
            )
            checks["split_invoice_check"] = CheckResult(status=CheckStatus.PASS, reason=f"Invoice type: {split_info.invoice_type}.")

            if p.total_amount is not None:
                tol = check_tolerance(split_info.cumulative_invoiced or p.total_amount, po.po_amount, tolerance_type, tolerance_value)
                if split_info.invoice_type == "PARTIAL_INVOICE":
                    # A partial/split invoice is *expected* to be under the PO amount
                    # until the sequence completes -- only overbilling the PO is a failure.
                    over_billed = split_info.cumulative_invoiced > (po.po_amount + tol.allowed_difference)
                    checks["tolerance_check"] = (
                        CheckResult(
                            status=CheckStatus.FAIL,
                            expected=po.po_amount,
                            actual=split_info.cumulative_invoiced,
                            difference=tol.difference,
                            reason=f"Cumulative invoiced amount {split_info.cumulative_invoiced} exceeds PO amount "
                            f"{po.po_amount} plus the allowed {tolerance_type} tolerance of {tol.allowed_difference}.",
                        )
                        if over_billed
                        else CheckResult(
                            status=CheckStatus.PASS,
                            expected=po.po_amount,
                            actual=split_info.cumulative_invoiced,
                            difference=tol.difference,
                            reason=f"Cumulative invoiced amount {split_info.cumulative_invoiced} is a legitimate partial "
                            f"invoice against PO amount {po.po_amount} (not overbilled).",
                        )
                    )
                else:
                    checks["tolerance_check"] = (
                        CheckResult(
                            status=CheckStatus.PASS,
                            expected=po.po_amount,
                            actual=split_info.cumulative_invoiced,
                            difference=tol.difference,
                            reason=f"Invoiced amount is within the vendor's {tolerance_type} tolerance "
                            f"(allowed difference {tol.allowed_difference}).",
                        )
                        if tol.within_tolerance
                        else CheckResult(
                            status=CheckStatus.FAIL,
                            expected=po.po_amount,
                            actual=split_info.cumulative_invoiced,
                            difference=tol.difference,
                            reason=f"Invoiced amount {split_info.cumulative_invoiced} differs from PO amount "
                            f"{po.po_amount} by {tol.difference}, exceeding the allowed {tolerance_type} tolerance of "
                            f"{tol.allowed_difference}.",
                        )
                    )
                amount_analysis = AmountAnalysis(
                    invoice_total=p.total_amount,
                    po_total=po.po_amount,
                    difference=tol.difference,
                    allowed_tolerance=tol.allowed_difference,
                    tolerance_type=tolerance_type,
                )
                steps.append(f"Tolerance calculated: allowed={tol.allowed_difference}, actual_difference={tol.difference}.")
            else:
                checks["tolerance_check"] = CheckResult(status=CheckStatus.NOT_CHECKED, reason="Invoice total amount is missing; tolerance could not be evaluated.")
                amount_analysis = AmountAnalysis(invoice_total=None, po_total=po.po_amount)

            matched_po_model = MatchedPO(
                po_number=po.po_number,
                spreadsheet_row=po.spreadsheet_row,
                vendor=po.vendor_name,
                match_method=match_result.match_method,
                match_confidence=match_result.match_confidence,
                po_snapshot=po.model_dump(),
            )
        else:
            status = CheckStatus.WARNING if match_result.match_method == "ambiguous" else CheckStatus.FAIL
            checks["po_number_match"] = (
                CheckResult(status=CheckStatus.NOT_CHECKED, reason="No PO number present on invoice.")
                if not d.po_number
                else CheckResult(status=CheckStatus.FAIL, reason=f"PO number '{d.po_number}' did not match any PO on file.")
            )
            checks["po_match"] = CheckResult(status=status, reason=match_result.reason)
            checks["vendor_po_identity_conflict"] = CheckResult(status=CheckStatus.PASS, reason="Not applicable: no PO matched.")
            checks["line_item_match"] = CheckResult(status=CheckStatus.NOT_CHECKED, reason="No matched PO to compare line items against.")
            checks["quantity_match"] = CheckResult(status=CheckStatus.NOT_CHECKED, reason="No matched PO to compare quantities against.")
            checks["unit_price_match"] = CheckResult(status=CheckStatus.NOT_CHECKED, reason="No matched PO to compare unit prices against.")
            checks["tolerance_check"] = CheckResult(status=CheckStatus.NOT_CHECKED, reason="No matched PO; tolerance could not be evaluated.")
            checks["split_invoice_check"] = CheckResult(status=CheckStatus.NOT_CHECKED, reason="No matched PO; split-invoice state could not be evaluated.")
            amount_analysis = AmountAnalysis(invoice_total=p.total_amount, po_total=None)

        outcome = decide(checks=checks, duplicate=duplicate, vendor=vendor_info, match_result=match_result, split_info=split_info)
        steps.append(f"Decision generated: {outcome.decision.value} - {outcome.reason}")

        result = DecisionResult(
            decision=outcome.decision,
            reason=outcome.reason,
            checks=checks,
            invoice_extraction=invoice.model_dump(),
            matched_po=matched_po_model,
            po_candidates=match_result.candidates,
            amount_analysis=amount_analysis,
            duplicate=duplicate,
            vendor=vendor_info,
            split_invoice=split_info,
            audit=AuditTrail(processing_steps=steps, document_hash=document_hash, extraction_method=invoice.extraction_metadata.method),
        )

        if self.settings.enable_exception_agent and outcome.decision == Decision.REVIEW:
            context = build_context_summary(checks=checks, po_candidates=match_result.candidates, duplicate=duplicate, split_info=split_info, vendor=vendor_info)
            result.ai_exception_analysis = investigate(
                context_summary=context,
                model=self.settings.exception_agent_model,
                base_url=self.settings.ollama_base_url,
                timeout_seconds=self.settings.vision_request_timeout_seconds,
            )
            steps.append("Optional exception agent invoked for REVIEW case (advisory only; did not change the decision).")

        self._persist(
            invoice_id=d.invoice_number or f"HASH-{document_hash[:12]}",
            file_name=file_name,
            vendor_name=d.vendor_name or "",
            invoice_number=d.invoice_number or "",
            invoice_date=d.invoice_date,
            po_number=matched_po_model.po_number if matched_po_model else d.po_number,
            total_amount=p.total_amount,
            document_hash=document_hash,
            result=result,
        )
        return result

    def _persist(
        self,
        invoice_id: str,
        file_name: str,
        vendor_name: str,
        invoice_number: str,
        invoice_date: str | None,
        po_number: str | None,
        total_amount: float | None,
        document_hash: str,
        result: DecisionResult,
    ) -> None:
        self.ledger.insert(
            invoice_id=invoice_id,
            file_name=file_name,
            vendor_name=vendor_name,
            vendor_name_normalized=normalize_vendor_name(vendor_name),
            invoice_number=invoice_number,
            invoice_number_normalized=normalize_invoice_number(invoice_number),
            invoice_date=invoice_date,
            po_number=po_number,
            po_number_normalized=normalize_po_number(po_number) if po_number else None,
            total_amount=total_amount,
            document_hash=document_hash,
            decision=result.decision.value,
            reason=result.reason,
            result_json=result.model_dump(),
        )

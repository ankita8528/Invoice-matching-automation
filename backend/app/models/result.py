"""Pydantic schema for the final /api/decide response."""
from __future__ import annotations

from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field


class CheckStatus(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    WARNING = "WARNING"
    NOT_CHECKED = "NOT_CHECKED"


class Decision(str, Enum):
    APPROVE = "APPROVE"
    # The Python identifier stays APPROVE_PARTIAL (so code reads naturally),
    # but the actual decision string returned by the API / stored in the
    # cache is "Accept/partial payment" per explicit request.
    APPROVE_PARTIAL = "Accept/partial payment"
    REVIEW = "REVIEW"
    REJECT = "REJECT"


class CheckResult(BaseModel):
    status: CheckStatus
    expected: Optional[Any] = None
    actual: Optional[Any] = None
    difference: Optional[Any] = None
    reason: str = ""


class POCandidate(BaseModel):
    po_number: str
    score: float
    reasons: list[str] = Field(default_factory=list)


class MatchedPO(BaseModel):
    po_number: Optional[str] = None
    spreadsheet_row: Optional[int] = None
    vendor: Optional[str] = None
    match_method: str = "none"
    match_confidence: float = 0.0
    po_snapshot: Optional[dict] = None


class AmountAnalysis(BaseModel):
    invoice_total: Optional[float] = None
    po_total: Optional[float] = None
    difference: Optional[float] = None
    allowed_tolerance: Optional[float] = None
    tolerance_type: Optional[str] = None


class SplitInvoiceInfo(BaseModel):
    invoice_type: str = "FULL_INVOICE"  # FULL_INVOICE | PARTIAL_INVOICE
    po_amount: Optional[float] = None
    previously_invoiced: Optional[float] = None
    current_invoice: Optional[float] = None
    cumulative_invoiced: Optional[float] = None
    remaining_balance: Optional[float] = None


class VendorInfo(BaseModel):
    vendor_id: Optional[str] = None
    matched_name: Optional[str] = None
    status: str = "UNKNOWN"  # APPROVED | NOT_APPROVED | UNKNOWN
    match_confidence: float = 0.0
    tolerance_type: Optional[str] = None
    tolerance_value: Optional[float] = None


class AuditTrail(BaseModel):
    processing_steps: list[str] = Field(default_factory=list)
    document_hash: Optional[str] = None
    extraction_method: Optional[str] = None


class DecisionResult(BaseModel):
    decision: Decision
    reason: str
    checks: dict[str, CheckResult] = Field(default_factory=dict)
    invoice_extraction: Optional[dict] = None
    matched_po: Optional[MatchedPO] = None
    po_candidates: list[POCandidate] = Field(default_factory=list)
    amount_analysis: Optional[AmountAnalysis] = None
    vendor: Optional[VendorInfo] = None
    split_invoice: Optional[SplitInvoiceInfo] = None
    ai_exception_analysis: Optional[dict] = None
    audit: AuditTrail = Field(default_factory=AuditTrail)

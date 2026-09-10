"""Pydantic schema for a structured invoice, as produced by extraction.

This is the ONE shape both the digital-text parser and the OCR+vision
parser must normalize into. Never invent values: a field that can't be
reliably read is `None`, not a guess.
"""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field


class InvoiceLineItem(BaseModel):
    item_name: Optional[str] = None
    description: Optional[str] = None
    quantity: Optional[float] = None
    unit_price: Optional[float] = None
    amount: Optional[float] = None


class InvoiceDetails(BaseModel):
    vendor_name: Optional[str] = None
    invoice_number: Optional[str] = None
    invoice_date: Optional[str] = None
    po_number: Optional[str] = None


class PaymentDetails(BaseModel):
    subtotal_amount: Optional[float] = None
    tax_amount: Optional[float] = None
    total_amount: Optional[float] = None


class ExtractionMetadata(BaseModel):
    method: str = "pymupdf"
    confidence: Optional[float] = None
    warnings: list[str] = Field(default_factory=list)


class StructuredInvoice(BaseModel):
    invoice_details: InvoiceDetails = Field(default_factory=InvoiceDetails)
    line_items: list[InvoiceLineItem] = Field(default_factory=list)
    payment_details: PaymentDetails = Field(default_factory=PaymentDetails)
    extraction_metadata: ExtractionMetadata = Field(default_factory=ExtractionMetadata)

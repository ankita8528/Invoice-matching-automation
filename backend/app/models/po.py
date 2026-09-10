"""Pydantic schema for Purchase Orders loaded from the PO spreadsheet."""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field


class POLineItem(BaseModel):
    item_name: Optional[str] = None
    description: Optional[str] = None
    quantity: Optional[float] = None
    unit_price: Optional[float] = None
    amount: Optional[float] = None
    spreadsheet_row: Optional[int] = None


class PurchaseOrder(BaseModel):
    po_number: str
    po_number_normalized: str
    vendor_name: str
    vendor_name_normalized: str
    po_date: Optional[str] = None
    currency: str = "INR"
    status: str = "OPEN"
    po_amount: float = 0.0
    # Optional PO-level tolerance override (takes precedence over the vendor's
    # default tolerance when present -- some datasets specify tolerance per
    # PO, e.g. the same vendor having a 2% tolerance on one PO and 1% on another).
    tolerance_type: Optional[str] = None
    tolerance_value: Optional[float] = None
    line_items: list[POLineItem] = Field(default_factory=list)
    # Row number of the FIRST spreadsheet row this PO appeared on (1-indexed,
    # matching what a human would see if they opened the .xlsx in Excel).
    spreadsheet_row: int = 0
    # Every row (multi-line POs may span several rows).
    all_spreadsheet_rows: list[int] = Field(default_factory=list)

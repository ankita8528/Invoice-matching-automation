"""Loads the PO and vendor master spreadsheets into in-memory Pydantic/
dataclass objects, preserving original Excel row numbers (never relying on
row number alone -- the PO number and a full snapshot travel with every
match, see models/po.py).

Data is cached and refreshed automatically if the underlying file's mtime
changes, so editing the spreadsheet doesn't require an app restart.
"""
from __future__ import annotations

import time
from pathlib import Path

import pandas as pd

from app.matching.normalization import normalize_po_number, normalize_vendor_name
from app.models.po import POLineItem, PurchaseOrder
from app.validation.vendor_validator import VendorRecord


class DataFileMissingError(Exception):
    pass


def load_purchase_orders(path: Path) -> list[PurchaseOrder]:
    if not path.exists():
        raise DataFileMissingError(f"PO spreadsheet not found at {path}")

    df = pd.read_excel(path, dtype=str)
    df.columns = [str(c).strip() for c in df.columns]

    def col(row, *names):
        for n in names:
            if n in row and pd.notna(row[n]):
                return row[n]
        return None

    grouped: dict[str, PurchaseOrder] = {}
    for excel_row_idx, row in enumerate(df.to_dict(orient="records"), start=2):  # header is row 1
        po_number = col(row, "PO Number")
        if not po_number:
            continue
        po_number = str(po_number).strip()
        po_number_norm = normalize_po_number(po_number)

        vendor_name = str(col(row, "Vendor Name") or "").strip()
        quantity = _to_float(col(row, "Quantity"))
        unit_price = _to_float(col(row, "Unit Price"))
        amount = _to_float(col(row, "PO Amount"))
        if amount is None and quantity is not None and unit_price is not None:
            amount = round(quantity * unit_price, 2)

        line_item = POLineItem(
            item_name=col(row, "Item"),
            description=col(row, "Description"),
            quantity=quantity,
            unit_price=unit_price,
            amount=amount,
            spreadsheet_row=excel_row_idx,
        )

        if po_number_norm not in grouped:
            grouped[po_number_norm] = PurchaseOrder(
                po_number=po_number,
                po_number_normalized=po_number_norm,
                vendor_name=vendor_name,
                vendor_name_normalized=normalize_vendor_name(vendor_name),
                po_date=str(col(row, "PO Date")) if col(row, "PO Date") else None,
                currency=str(col(row, "Currency") or "INR"),
                status=str(col(row, "Status") or "OPEN"),
                po_amount=0.0,
                tolerance_type=(str(col(row, "Tolerance Type")).strip().lower() if col(row, "Tolerance Type") else None),
                tolerance_value=_to_float(col(row, "Tolerance Value")),
                line_items=[],
                spreadsheet_row=excel_row_idx,
                all_spreadsheet_rows=[],
            )
        po = grouped[po_number_norm]
        po.line_items.append(line_item)
        po.po_amount = round(po.po_amount + (amount or 0.0), 2)
        po.all_spreadsheet_rows.append(excel_row_idx)

    return list(grouped.values())


def load_vendors(path: Path) -> list[VendorRecord]:
    if not path.exists():
        raise DataFileMissingError(f"Vendor spreadsheet not found at {path}")

    df = pd.read_excel(path, dtype=str)
    df.columns = [str(c).strip() for c in df.columns]

    vendors: list[VendorRecord] = []
    for row in df.to_dict(orient="records"):
        name = str(row.get("vendor_name") or "").strip()
        if not name:
            continue
        vendors.append(
            VendorRecord(
                vendor_id=str(row.get("vendor_id") or "").strip(),
                vendor_name=name,
                vendor_name_normalized=normalize_vendor_name(name),
                status=str(row.get("status") or "UNKNOWN").strip().upper(),
                tolerance_type=str(row.get("tolerance_type") or "percentage").strip().lower(),
                tolerance_value=_to_float(row.get("tolerance_value")) or 0.0,
            )
        )
    return vendors


def _to_float(value) -> float | None:
    if value is None:
        return None
    try:
        if isinstance(value, str):
            value = value.replace(",", "").replace("₹", "").replace("$", "").strip()
            if value == "" or value.lower() == "nan":
                return None
        return round(float(value), 2)
    except (ValueError, TypeError):
        return None


class DataStore:
    """Simple mtime-aware in-memory cache for PO/vendor spreadsheets."""

    def __init__(self, po_path: Path, vendor_path: Path):
        self.po_path = po_path
        self.vendor_path = vendor_path
        self._po_mtime: float | None = None
        self._vendor_mtime: float | None = None
        self._pos: list[PurchaseOrder] = []
        self._vendors: list[VendorRecord] = []

    def get_purchase_orders(self) -> list[PurchaseOrder]:
        mtime = self.po_path.stat().st_mtime if self.po_path.exists() else None
        if mtime != self._po_mtime:
            self._pos = load_purchase_orders(self.po_path)
            self._po_mtime = mtime
        return self._pos

    def get_vendors(self) -> list[VendorRecord]:
        mtime = self.vendor_path.stat().st_mtime if self.vendor_path.exists() else None
        if mtime != self._vendor_mtime:
            self._vendors = load_vendors(self.vendor_path)
            self._vendor_mtime = mtime
        return self._vendors

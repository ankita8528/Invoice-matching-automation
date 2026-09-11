"""Simple Streamlit showcase UI for the invoice AP-matching backend.

This is a lightweight alternative to frontend/ (React+Vite) for quickly
demoing the system without a Node.js toolchain. It is a pure client of the
same POST /api/decide endpoint -- no business logic lives here.

Run:
    streamlit run streamlit_app.py
"""
from __future__ import annotations

import io
import os

import fitz  # PyMuPDF
import requests
import streamlit as st
from PIL import Image

API_BASE_URL = os.environ.get("API_BASE_URL", "http://localhost:8000")

DECISION_COLORS = {
    "APPROVE": ("#0f5132", "#d1e7dd", "🟢"),
    "APPROVE_PARTIAL": ("#084298", "#cfe2ff", "🔵"),
    "REVIEW": ("#664d03", "#fff3cd", "🟡"),
    "REJECT": ("#842029", "#f8d7da", "🔴"),
}
CHECK_ICON = {"PASS": "✅", "FAIL": "❌", "WARNING": "⚠️", "NOT_CHECKED": "⬜"}

st.set_page_config(page_title="Invoice Processing", page_icon="🧾", layout="wide")

st.markdown(
    """
    <style>
      .block-container { padding-top: 2rem; max-width: 1500px; }
      .decision-badge {
          display: inline-flex; align-items: center; gap: 10px;
          font-size: 1.3rem; font-weight: 700; padding: 10px 20px;
          border-radius: 999px; margin-bottom: 6px;
      }
      .reason-text { font-size: 0.95rem; margin: 4px 0 0; color: #444; }
      .section-title {
          font-size: 0.75rem; font-weight: 700; text-transform: uppercase;
          letter-spacing: 0.05em; color: #6b6b74; margin: 16px 0 6px;
      }
      .field-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 6px 20px; font-size: 0.85rem; }
      .field-grid .label { color: #6b6b74; font-size: 0.72rem; }
      .field-grid .value { font-weight: 600; }
      .items-table { width: 100%; border-collapse: collapse; font-size: 0.82rem; }
      .items-table th, .items-table td { text-align: left; padding: 4px 8px; border-bottom: 1px solid #eee; }
      .check-row { padding: 6px 10px; border-radius: 6px; margin-bottom: 3px; font-size: 0.82rem; }
      .check-fail { background: #f8d7da; }
      .check-warning { background: #fff3cd; }
      .check-pass { background: transparent; }
      .check-not_checked { opacity: 0.55; }
    </style>
    """,
    unsafe_allow_html=True,
)

st.title("🧾 Invoice Processing")
st.caption(f"Backend: {API_BASE_URL}")

uploaded = st.file_uploader("Upload Invoice PDF", type=["pdf"])

if uploaded is not None and uploaded.file_id != st.session_state.get("last_file_id"):
    st.session_state["pending_bytes"] = uploaded.getvalue()
    st.session_state["pending_name"] = uploaded.name
    st.session_state["last_file_id"] = uploaded.file_id
    st.session_state.pop("result", None)

if "pending_bytes" in st.session_state:
    if st.button("Process Invoice", type="primary"):
        with st.spinner("Processing..."):
            try:
                resp = requests.post(
                    f"{API_BASE_URL}/api/decide",
                    files={"file": (st.session_state["pending_name"], st.session_state["pending_bytes"], "application/pdf")},
                    timeout=180,
                )
            except requests.exceptions.ConnectionError:
                st.error(f"Could not reach the backend at {API_BASE_URL}. Is `uvicorn app.main:app` running?")
                st.stop()

        if resp.status_code >= 400:
            st.error(f"Server error ({resp.status_code}): {resp.json().get('error', resp.text)}")
            st.stop()

        st.session_state["result"] = resp.json()

result = st.session_state.get("result")
pdf_bytes = st.session_state.get("pending_bytes")

if pdf_bytes is None:
    st.info("Upload an invoice PDF above to get started.")
    st.stop()

col_pdf, col_results = st.columns([1.6, 1], gap="large")

with col_pdf:
    st.markdown('<p class="section-title">Document Preview</p>', unsafe_allow_html=True)
    try:
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        for page in doc:
            pix = page.get_pixmap(matrix=fitz.Matrix(2.2, 2.2))
            img = Image.open(io.BytesIO(pix.tobytes("png")))
            st.image(img, use_container_width=True)
        doc.close()
    except Exception as exc:  # noqa: BLE001
        st.warning(f"Could not render PDF preview: {exc}")

with col_results:
    if result is None:
        st.info("Click **Process Invoice** to run it through the pipeline.")
    else:
        decision = result.get("decision", "UNKNOWN")
        text_color, bg_color, emoji = DECISION_COLORS.get(decision, ("#333", "#eee", "❔"))
        st.markdown(
            f'<div class="decision-badge" style="color:{text_color};background:{bg_color};">{emoji} {decision}</div>'
            f'<p class="reason-text">{result.get("reason", "")}</p>',
            unsafe_allow_html=True,
        )

        extraction = result.get("invoice_extraction") or {}
        details = extraction.get("invoice_details") or {}
        payment = extraction.get("payment_details") or {}
        line_items = extraction.get("line_items") or []

        def _fmt(v):
            return v if v not in (None, "") else "—"

        st.markdown('<p class="section-title">Extracted Values</p>', unsafe_allow_html=True)
        st.markdown(
            f"""
            <div class="field-grid">
              <div><div class="label">Vendor</div><div class="value">{_fmt(details.get('vendor_name'))}</div></div>
              <div><div class="label">Invoice Number</div><div class="value">{_fmt(details.get('invoice_number'))}</div></div>
              <div><div class="label">Invoice Date</div><div class="value">{_fmt(details.get('invoice_date'))}</div></div>
              <div><div class="label">PO Number</div><div class="value">{_fmt(details.get('po_number'))}</div></div>
              <div><div class="label">Subtotal</div><div class="value">{_fmt(payment.get('subtotal_amount'))}</div></div>
              <div><div class="label">Tax</div><div class="value">{_fmt(payment.get('tax_amount'))}</div></div>
              <div><div class="label">Total</div><div class="value">{_fmt(payment.get('total_amount'))}</div></div>
            </div>
            """,
            unsafe_allow_html=True,
        )

        if line_items:
            rows = "".join(
                f"<tr><td>{_fmt(li.get('item_name') or li.get('description'))}</td>"
                f"<td>{_fmt(li.get('quantity'))}</td><td>{_fmt(li.get('unit_price'))}</td>"
                f"<td>{_fmt(li.get('amount'))}</td></tr>"
                for li in line_items
            )
            st.markdown(
                f"""
                <table class="items-table">
                  <tr><th>Item</th><th>Qty</th><th>Unit Price</th><th>Amount</th></tr>
                  {rows}
                </table>
                """,
                unsafe_allow_html=True,
            )

        with st.expander("Full details (PO match, all checks, audit trail, raw JSON)"):
            matched_po = result.get("matched_po") or {}
            st.markdown("**Matched PO**")
            if matched_po.get("po_number"):
                amt = result.get("amount_analysis") or {}
                st.markdown(
                    f"- PO Number: {matched_po.get('po_number')}  \n"
                    f"- Spreadsheet Row: {matched_po.get('spreadsheet_row')}  \n"
                    f"- Match Method: {matched_po.get('match_method')} (confidence {matched_po.get('match_confidence', 0):.2f})  \n"
                    f"- Invoice Total: {amt.get('invoice_total')} vs PO Total: {amt.get('po_total')} "
                    f"(difference {amt.get('difference')}, allowed {amt.get('allowed_tolerance')})"
                )
            else:
                st.write("No purchase order was confidently matched.")
                candidates = result.get("po_candidates") or []
                if candidates:
                    st.write("Candidates considered:")
                    st.table(candidates)

            split_info = result.get("split_invoice") or {}
            if split_info.get("invoice_type") == "PARTIAL_INVOICE":
                st.markdown("**Split / Partial Invoice**")
                st.json(split_info)

            st.markdown("**Checks**")
            for name, check in (result.get("checks") or {}).items():
                status = check.get("status", "NOT_CHECKED")
                icon = CHECK_ICON.get(status, "❔")
                css_class = f"check-{status.lower()}"
                st.markdown(
                    f'<div class="check-row {css_class}"><b>{icon} {name.replace("_", " ")}</b> — {check.get("reason", "")}</div>',
                    unsafe_allow_html=True,
                )

            ai_note = result.get("ai_exception_analysis")
            if ai_note and ai_note.get("analysis"):
                st.markdown("**AI Exception Analysis (advisory only)**")
                st.info(ai_note["analysis"])
                if ai_note.get("suggested_next_action"):
                    st.write(f"**Suggested next action:** {ai_note['suggested_next_action']}")

            st.markdown("**Audit Trail**")
            for i, step in enumerate((result.get("audit") or {}).get("processing_steps", []), start=1):
                st.write(f"{i}. {step}")

            st.markdown("**Raw JSON response**")
            st.json(result)

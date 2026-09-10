function Field({ label, value }) {
  return (
    <div>
      <div className="kv-label">{label}</div>
      <div className="kv-value">{value ?? <span className="loading">(missing)</span>}</div>
    </div>
  );
}

export default function InvoiceDetails({ extraction }) {
  if (!extraction) return null;
  const details = extraction.invoice_details ?? {};
  const payment = extraction.payment_details ?? {};

  return (
    <div className="panel">
      <p className="section-title">Invoice Details</p>
      <div className="kv-grid">
        <Field label="Vendor" value={details.vendor_name} />
        <Field label="Invoice Number" value={details.invoice_number} />
        <Field label="Invoice Date" value={details.invoice_date} />
        <Field label="PO Number" value={details.po_number} />
        <Field label="Total" value={payment.total_amount != null ? payment.total_amount.toLocaleString() : null} />
        <Field
          label="Extraction Method"
          value={`${extraction.extraction_metadata?.method ?? "-"} (confidence ${extraction.extraction_metadata?.confidence ?? "-"})`}
        />
      </div>
    </div>
  );
}

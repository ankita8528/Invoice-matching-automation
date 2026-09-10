import { useState } from "react";
import { decideInvoice } from "./api.js";
import UploadForm from "./components/UploadForm.jsx";
import DecisionBadge from "./components/DecisionBadge.jsx";
import InvoiceDetails from "./components/InvoiceDetails.jsx";
import MatchedPO from "./components/MatchedPO.jsx";
import ChecksList from "./components/ChecksList.jsx";
import AuditTrail from "./components/AuditTrail.jsx";

export default function App() {
  const [result, setResult] = useState(null);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(false);

  async function handleUpload(file) {
    setLoading(true);
    setError(null);
    setResult(null);
    try {
      const data = await decideInvoice(file);
      setResult(data);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="app">
      <h1>Invoice Processing</h1>
      <p className="subtitle">Upload an invoice PDF to get an AI-assisted, deterministically-decided AP outcome.</p>

      <UploadForm onSubmit={handleUpload} loading={loading} />

      {error && <div className="error-banner">{error}</div>}

      {result && (
        <>
          <div className="panel">
            <DecisionBadge decision={result.decision} reason={result.reason} />
          </div>

          <InvoiceDetails extraction={result.invoice_extraction} />
          <MatchedPO matchedPo={result.matched_po} amountAnalysis={result.amount_analysis} poCandidates={result.po_candidates} />

          {result.split_invoice?.invoice_type === "PARTIAL_INVOICE" && (
            <div className="panel">
              <p className="section-title">Split Invoice</p>
              <div className="kv-grid">
                <div>
                  <div className="kv-label">PO Amount</div>
                  <div className="kv-value">{result.split_invoice.po_amount}</div>
                </div>
                <div>
                  <div className="kv-label">Previously Invoiced</div>
                  <div className="kv-value">{result.split_invoice.previously_invoiced}</div>
                </div>
                <div>
                  <div className="kv-label">Current Invoice</div>
                  <div className="kv-value">{result.split_invoice.current_invoice}</div>
                </div>
                <div>
                  <div className="kv-label">Cumulative Invoiced</div>
                  <div className="kv-value">{result.split_invoice.cumulative_invoiced}</div>
                </div>
                <div>
                  <div className="kv-label">Remaining Balance</div>
                  <div className="kv-value">{result.split_invoice.remaining_balance}</div>
                </div>
              </div>
            </div>
          )}

          <ChecksList checks={result.checks} />

          {result.ai_exception_analysis?.analysis && (
            <div className="panel">
              <p className="section-title">AI Exception Analysis (advisory only)</p>
              <p>{result.ai_exception_analysis.analysis}</p>
              {result.ai_exception_analysis.suggested_next_action && (
                <p>
                  <strong>Suggested next action:</strong> {result.ai_exception_analysis.suggested_next_action}
                </p>
              )}
            </div>
          )}

          <AuditTrail audit={result.audit} />
        </>
      )}
    </div>
  );
}

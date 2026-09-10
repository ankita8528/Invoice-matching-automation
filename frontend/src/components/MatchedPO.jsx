export default function MatchedPO({ matchedPo, amountAnalysis, poCandidates }) {
  if (!matchedPo?.po_number) {
    return (
      <div className="panel">
        <p className="section-title">Matched PO</p>
        <p>No purchase order was confidently matched.</p>
        {poCandidates?.length > 0 && (
          <>
            <p className="section-title" style={{ marginTop: 16 }}>
              Candidates considered
            </p>
            {poCandidates.map((c) => (
              <div className="candidate-row" key={c.po_number}>
                <span>{c.po_number}</span>
                <span>score {c.score.toFixed(2)}</span>
              </div>
            ))}
          </>
        )}
      </div>
    );
  }

  return (
    <div className="panel">
      <p className="section-title">Matched PO</p>
      <div className="kv-grid">
        <div>
          <div className="kv-label">PO Number</div>
          <div className="kv-value">{matchedPo.po_number}</div>
        </div>
        <div>
          <div className="kv-label">Spreadsheet Row</div>
          <div className="kv-value">{matchedPo.spreadsheet_row}</div>
        </div>
        <div>
          <div className="kv-label">Vendor</div>
          <div className="kv-value">{matchedPo.vendor}</div>
        </div>
        <div>
          <div className="kv-label">PO Amount</div>
          <div className="kv-value">{amountAnalysis?.po_total?.toLocaleString() ?? "-"}</div>
        </div>
        <div>
          <div className="kv-label">Match Method</div>
          <div className="kv-value">{matchedPo.match_method}</div>
        </div>
        <div>
          <div className="kv-label">Confidence</div>
          <div className="kv-value">{matchedPo.match_confidence?.toFixed(2)}</div>
        </div>
      </div>
      {amountAnalysis && (
        <div className="kv-grid" style={{ marginTop: 14 }}>
          <div>
            <div className="kv-label">Invoice Total</div>
            <div className="kv-value">{amountAnalysis.invoice_total ?? "-"}</div>
          </div>
          <div>
            <div className="kv-label">Difference</div>
            <div className="kv-value">{amountAnalysis.difference ?? "-"}</div>
          </div>
          <div>
            <div className="kv-label">Allowed Tolerance</div>
            <div className="kv-value">{amountAnalysis.allowed_tolerance ?? "-"}</div>
          </div>
        </div>
      )}
    </div>
  );
}

export default function AuditTrail({ audit }) {
  const steps = audit?.processing_steps ?? [];
  if (steps.length === 0) return null;

  return (
    <details className="panel" open>
      <summary>Audit Trail ({steps.length} steps)</summary>
      <ol className="audit-list">
        {steps.map((step, i) => (
          <li key={i}>{step}</li>
        ))}
      </ol>
    </details>
  );
}

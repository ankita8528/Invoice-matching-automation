const ICON = {
  PASS: "✓",
  FAIL: "✗",
  WARNING: "!",
  NOT_CHECKED: "–",
};

export default function ChecksList({ checks }) {
  const entries = Object.entries(checks ?? {});
  if (entries.length === 0) return null;

  return (
    <div className="panel">
      <p className="section-title">Checks</p>
      <ul className="checks-list">
        {entries.map(([name, result]) => (
          <li className={`check-item status-${result.status}`} key={name}>
            <span className="check-icon">{ICON[result.status] ?? "?"}</span>
            <span>
              <span className="check-name">{name.replaceAll("_", " ")}</span>
              {result.reason && <div className="check-reason">{result.reason}</div>}
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}

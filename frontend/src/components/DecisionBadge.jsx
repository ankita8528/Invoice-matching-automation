const ICONS = {
  APPROVE: "\u{1F7E2}",
  APPROVE_PARTIAL: "\u{1F535}",
  REVIEW: "\u{1F7E1}",
  REJECT: "\u{1F534}",
};

export default function DecisionBadge({ decision, reason }) {
  return (
    <div>
      <div className={`decision-badge decision-${decision}`}>
        <span>{ICONS[decision] ?? ""}</span>
        <span>{decision}</span>
      </div>
      <p className="reason">{reason}</p>
    </div>
  );
}

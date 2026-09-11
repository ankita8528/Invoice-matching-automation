// Keyed by the actual decision string the API returns. CSS class names can't
// safely contain spaces/slashes (e.g. "Accept/partial payment"), so each
// entry carries a stable "slug" used only for the CSS class, separate from
// the human-readable text that's actually displayed.
const DECISION_STYLE = {
  APPROVE: { icon: "\u{1F7E2}", slug: "APPROVE" },
  "Accept/partial payment": { icon: "\u{1F535}", slug: "APPROVE_PARTIAL" },
  REVIEW: { icon: "\u{1F7E1}", slug: "REVIEW" },
  REJECT: { icon: "\u{1F534}", slug: "REJECT" },
};

export default function DecisionBadge({ decision, reason }) {
  const style = DECISION_STYLE[decision] ?? { icon: "❔", slug: "UNKNOWN" };
  return (
    <div>
      <div className={`decision-badge decision-${style.slug}`}>
        <span>{style.icon}</span>
        <span>{decision}</span>
      </div>
      <p className="reason">{reason}</p>
    </div>
  );
}

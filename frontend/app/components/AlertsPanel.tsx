import type { Alert } from "../lib/api";

const ROLES = ["EM", "TL", "PM", "IC"] as const;

export function AlertsPanel({
  alerts,
  role,
  onRoleChange,
}: {
  alerts: Alert[];
  role: string;
  onRoleChange: (role: string) => void;
}) {
  return (
    <div className="panel">
      <h2>Alerts &amp; digest</h2>
      <div className="controls">
        <div>
          <label htmlFor="role">Recipient role</label>
          <select id="role" value={role} onChange={(e) => onRoleChange(e.target.value)}>
            {ROLES.map((r) => (
              <option key={r} value={r}>{r}</option>
            ))}
          </select>
        </div>
      </div>
      {alerts.length === 0 && <p className="muted">No alerts for this role.</p>}
      {alerts.map((a, i) => (
        <div className={`alert ${a.severity}`} key={`${a.type}:${a.subject}:${i}`}>
          <div className="head">
            <span className="sev">{a.severity}</span>
            <strong>{a.type}</strong>
            <span className="chip">{a.subject}</span>
            {a.owner && <span className="muted">owner: {a.owner}</span>}
          </div>
          <p className="muted">{a.recommended_action}</p>
          {a.reasons.length > 0 && (
            <p className="muted">reasons: {a.reasons.join(", ")}</p>
          )}
        </div>
      ))}
    </div>
  );
}

import type { ProjectScore } from "../lib/api";

export function ScoreBreakdown({ score }: { score: ProjectScore }) {
  return (
    <div className="panel">
      <h2>Score breakdown</h2>
      {score.sub_scores.map((s) => (
        <div className="subrow" key={s.name}>
          <div className="label">
            <span>{s.name}</span>
            <span className="muted">
              {s.score.toFixed(0)} · weight {s.weight.toFixed(2)} · {s.flag_count} flag(s)
            </span>
          </div>
          <div className="bar">
            <span style={{ width: `${Math.max(0, Math.min(100, s.score))}%` }} />
          </div>
          {s.contributors.length > 0 && (
            <p className="muted">{s.contributors.join(", ")}</p>
          )}
        </div>
      ))}
    </div>
  );
}

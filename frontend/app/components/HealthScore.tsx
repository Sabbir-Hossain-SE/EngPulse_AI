import type { ProjectScore } from "../lib/api";

const bandClass = (band: string): string => band.replace(/\s/g, "");

export function HealthScore({ score }: { score: ProjectScore }) {
  return (
    <div className="panel">
      <h2>Project health</h2>
      <div className="score-hero">
        <span className="score-num">{score.composite.toFixed(0)}</span>
        <span className={`band ${bandClass(score.band)}`}>{score.band}</span>
      </div>
      <p className="muted">{score.project}</p>
    </div>
  );
}

import type { KnowledgeReport } from "../lib/api";

export function KnowledgeMap({ report }: { report: KnowledgeReport }) {
  return (
    <div className="panel">
      <h2>Ownership &amp; bus factor</h2>
      {report.modules.length === 0 && <p className="muted">No modules indexed.</p>}
      {report.modules.map((m) => (
        <div className="subrow" key={m.module}>
          <div className="label">
            <span className={m.flags.length > 0 ? "spof" : ""}>{m.module}</span>
            <span className="muted">
              {m.owner ?? "—"} · {m.commit_count} commit(s) · {m.contributor_count} owner(s)
            </span>
          </div>
          {m.flags.length > 0 && (
            <p className="spof">⚠ single point of failure</p>
          )}
        </div>
      ))}
    </div>
  );
}

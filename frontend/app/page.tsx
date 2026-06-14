"use client";

import { useCallback, useEffect, useState } from "react";
import {
  getAlerts,
  getKnowledge,
  getProjects,
  getScore,
  type Alert,
  type KnowledgeReport,
  type Project,
  type ProjectScore,
} from "./lib/api";
import { HealthScore } from "./components/HealthScore";
import { ScoreBreakdown } from "./components/ScoreBreakdown";
import { AlertsPanel } from "./components/AlertsPanel";
import { KnowledgeMap } from "./components/KnowledgeMap";
import { AskBox } from "./components/AskBox";

const TEAM = "PAY";
const AS_OF = "2026-06-14";

export default function Dashboard() {
  const [projects, setProjects] = useState<Project[]>([]);
  const [repo, setRepo] = useState<string>("acme/payments");
  const [role, setRole] = useState<string>("EM");
  const [score, setScore] = useState<ProjectScore | null>(null);
  const [alerts, setAlerts] = useState<Alert[]>([]);
  const [knowledge, setKnowledge] = useState<KnowledgeReport | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    getProjects()
      .then((ps) => {
        setProjects(ps);
        if (ps.length > 0 && !ps.some((p) => p.repo === repo)) setRepo(ps[0].repo);
      })
      .catch((e) => setError(e.message));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const loadAlerts = useCallback(() => {
    getAlerts(repo, TEAM, role, AS_OF)
      .then((r) => setAlerts(r.alerts))
      .catch((e) => setError(e.message));
  }, [repo, role]);

  useEffect(() => {
    if (!repo) return;
    setError(null);
    getScore(repo, TEAM, AS_OF).then(setScore).catch((e) => setError(e.message));
    getKnowledge(repo).then(setKnowledge).catch((e) => setError(e.message));
    loadAlerts();
  }, [repo, loadAlerts]);

  return (
    <>
      <div className="controls">
        <div>
          <label htmlFor="repo">Project</label>
          <select id="repo" value={repo} onChange={(e) => setRepo(e.target.value)}>
            {projects.length === 0 && <option value={repo}>{repo}</option>}
            {projects.map((p) => (
              <option key={p.repo} value={p.repo}>{p.repo}</option>
            ))}
          </select>
        </div>
        <div>
          <label>As of</label>
          <input value={AS_OF} readOnly />
        </div>
      </div>

      {error && <p className="error">API error: {error} — is the API running on :8000?</p>}

      {score && (
        <div className="grid">
          <HealthScore score={score} />
          <ScoreBreakdown score={score} />
        </div>
      )}

      <AlertsPanel alerts={alerts} role={role} onRoleChange={setRole} />
      {knowledge && <KnowledgeMap report={knowledge} />}
      <AskBox repo={repo} team={TEAM} asOf={AS_OF} />
    </>
  );
}

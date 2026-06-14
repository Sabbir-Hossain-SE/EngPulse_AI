// Typed client for the EngPulse FastAPI service.

const BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export interface Project {
  repo: string;
  health_score: number | null;
  band: string | null;
}

export interface SubScore {
  name: string;
  score: number;
  weight: number;
  penalty: number;
  flag_count: number;
  contributors: string[];
}

export interface ProjectScore {
  project: string;
  composite: number;
  band: string;
  sub_scores: SubScore[];
}

export interface Alert {
  type: string;
  severity: string;
  roles: string[];
  subject: string;
  owner: string | null;
  reasons: string[];
  recommended_action: string;
  confidence: number;
  evidence: Record<string, unknown>;
}

export interface AlertsResponse {
  project: string;
  composite: number;
  band: string;
  alerts: Alert[];
}

export interface OwnershipEntry {
  module: string;
  owner: string | null;
  contributors: string[];
  contributor_count: number;
  commit_count: number;
  ownership_share: number;
  flags: string[];
}

export interface KnowledgeReport {
  repo: string;
  modules: OwnershipEntry[];
  flags: { type: string; severity: string; module: string }[];
}

export interface AgentAnswer {
  question: string;
  answer: string | null;
  citations: string[];
  confidence: number;
  abstained: boolean;
  clarifying_question: string | null;
  plan: { tool: string; evidence_count: number }[];
}

export interface AskRequest {
  question: string;
  repo: string;
  team?: string | null;
  as_of?: string | null;
}

async function getJSON<T>(path: string): Promise<T> {
  const resp = await fetch(`${BASE}${path}`);
  if (!resp.ok) throw new Error(`API ${resp.status} for ${path}`);
  return resp.json() as Promise<T>;
}

const qs = (params: Record<string, string | undefined>): string =>
  Object.entries(params)
    .filter(([, v]) => v != null && v !== "")
    .map(([k, v]) => `${k}=${encodeURIComponent(v as string)}`)
    .join("&");

export const getProjects = () => getJSON<Project[]>("/projects");

export const getScore = (repo: string, team?: string, asOf?: string) =>
  getJSON<ProjectScore>(`/score?${qs({ repo, team, as_of: asOf })}`);

export const getAlerts = (repo: string, team?: string, role?: string, asOf?: string) =>
  getJSON<AlertsResponse>(`/alerts?${qs({ repo, team, role, as_of: asOf })}`);

export const getKnowledge = (repo: string) =>
  getJSON<KnowledgeReport>(`/knowledge?${qs({ repo })}`);

// Stream the agent's reasoning stages over SSE (fetch + ReadableStream).
export async function askStream(
  req: AskRequest,
  onEvent: (event: Record<string, unknown>) => void,
): Promise<void> {
  const resp = await fetch(`${BASE}/ask/stream`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(req),
  });
  if (!resp.body) throw new Error("No response body for /ask/stream");

  const reader = resp.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const frames = buffer.split("\n\n");
    buffer = frames.pop() ?? "";
    for (const frame of frames) {
      const dataLine = frame.split("\n").find((l) => l.startsWith("data:"));
      if (!dataLine) continue;
      try {
        onEvent(JSON.parse(dataLine.slice(5).trim()));
      } catch {
        /* ignore malformed frame */
      }
    }
  }
}

# EngPulse dashboard

A role-based React/Next.js (App Router) dashboard over the EngPulse FastAPI
service: project health score + breakdown, role-filtered alerts/digest, the
ownership / bus-factor map, and a streaming **Ask EngPulse** box (SSE).

## Run

1. Start the API (from the repo root):
   ```bash
   uvicorn engpulse.api.main:app --port 8000
   ```
   (It defaults to the `fake` LLM backend, so no Ollama is required for the demo.)

2. Start the dashboard:
   ```bash
   cd frontend
   npm install
   npm run dev          # http://localhost:3000
   ```

The API base URL is configurable via `NEXT_PUBLIC_API_URL` (default
`http://localhost:8000`). The API allows the dashboard origin via CORS
(`DASHBOARD_URL`, default `http://localhost:3000`).

## Structure

```
app/
  layout.tsx           # shell
  page.tsx             # dashboard (project/role state, data loading)
  lib/api.ts           # typed API client (+ SSE for /ask/stream)
  components/
    HealthScore.tsx    # composite + band
    ScoreBreakdown.tsx # sub-scores
    AlertsPanel.tsx    # role-filtered alerts
    KnowledgeMap.tsx   # ownership / SPOF
    AskBox.tsx         # streaming Ask EngPulse
```

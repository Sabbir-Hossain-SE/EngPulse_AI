# EngPulse AI — Engineering Org Intelligence Command Center

An agentic, RAG-powered operating layer that connects **GitHub, GitHub Actions, and
Linear** to surface delivery risk, review bottlenecks, flaky tests, knowledge silos,
and ownership risk — as **grounded, evidence-cited insights**, a transparent
**0–100 health score**, role-based **alerts/digests**, and a natural-language
**"Ask EngPulse"** agent. It runs entirely on a self-hosted **Ollama** seam — no
data leaves your network — and every detector is **measured against a labeled set**.

> **Status:** MVP complete (Modules 1–8). 102 tests passing. The whole pipeline —
> ingest → resolve → detect → score → synthesize → ask → serve — runs **offline
> with zero services** via a deterministic fake-LLM backend and an in-memory DB.

### Headline results (on the labeled synthetic corpus)

| Capability | Metric |
|---|---|
| Stale-PR, flaky-test, deadline-drift, bus-factor detection | precision **1.00** / recall **1.00** |
| PR↔issue linking · GitHub↔Linear identity merge | precision **1.00** / recall **1.00** |
| Ask EngPulse: source recall · citation faithfulness · correct-abstention | **1.00** / **1.00** / **1.00** |
| Full evaluation re-run | **deterministic** (regression-guarded) |

See [Docs/EVAL_REPORT.md](Docs/EVAL_REPORT.md). The corpus is a **labeled seed** (a
handful of deliberately injected cases), so these numbers prove the *measurement
loop and the engine* work end-to-end — not that the system is at the PRD's
200-case target. The point is that **quality is scored, not asserted**, so it can't
silently regress.

---

## Core principle

**Deterministic facts are computed in code and are auditable; the language model
only retrieves, reasons, prioritizes, and summarizes — grounded in real records,
never inventing numbers.** Knowing where RAG belongs (ownership, context, Q&A) and
where it must *not* (hard metrics, severities, scores) is the central engineering
judgement this build demonstrates:

- Every **number** (review latency, flip rate, drift, bus factor, health score)
  comes from the metrics layer.
- Every **severity** comes from a deterministic flag, not the model.
- Every **LLM claim** must cite a retrieved source record, or it is dropped; if
  nothing grounds, the system **abstains**.

## Architecture

```
 Sources            Data Layer (deterministic)         Intelligence Layer            Surface
 ───────            ──────────────────────────         ──────────────────            ───────
 GitHub  ┐  connectors    normalize     entity         detectors (no LLM):           FastAPI
 Actions ├─▶(async,    ─▶ (pure DTO  ─▶ resolution ─┐  PR-flow · CI/test · delivery  ─▶ /score /alerts
 Linear  ┘  replayable)    → ORM)        PR↔issue   │  · bus-factor                     /digest
                                         ↔person     ├─▶ scoring (config 0–100 + band) ─▶ /ask (SSE)
                          unified Postgres ↔CI       │  alert router → EM/TL/PM/IC
                          schema + pgvector          │  ── AI layer (Ollama seam) ──    Next.js
                                                     ├─▶ hybrid RAG (vector+keyword     dashboard
                                                     │   +rerank, pgvector)
                                                     └─▶ grounded synthesis + Ask agent  Langfuse
                                                         (schema-enforced, abstaining)   tracing
```

Each module is a typed, independently testable unit; the AI layer sits on top of
proven facts, so its only job is to explain and prioritize what is already true.

---

## Quick start — offline, zero services

Everything below runs with **no Postgres, no Ollama, no network** (deterministic
fake LLM + in-memory DB), so you can see the whole system in seconds.

```bash
python3.12 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

pytest                                                   # 102 passing

engpulse evaluate                                        # score every detector + the agent
engpulse rag-demo  --query "who owns the auth tokens module"   # hybrid retrieval
engpulse synthesize                                      # a grounded, cited insight
engpulse ask "is the payments project at risk and who owns the risky module"
engpulse ask "what is the meaning of life"               # → abstains (no grounding)
```

`engpulse ask` plans which tools to call, gathers evidence across hops, and answers
with citations — or abstains / asks a clarifying question.

## Run the real stack

```bash
# 1. Infra (Postgres+pgvector, Redis, Langfuse, API, worker)
docker compose up -d            # or: docker-compose up -d

# 2. Ingest a repo + tracker, resolve entities (live or the bundled corpus)
engpulse init-db
engpulse ingest-github --repo acme/payments --source fixture --fixtures-dir datasets/synthetic
engpulse ingest-linear --team PAY            --source fixture --fixtures-dir datasets/synthetic
engpulse resolve

# 3. Inspect
engpulse score   --repo acme/payments --team PAY --as-of 2026-06-14 --persist
engpulse digest  --repo acme/payments --team PAY --role EM
engpulse knowledge --repo acme/payments

# 4. API + dashboard
uvicorn engpulse.api.main:app --port 8000
cd frontend && npm install && npm run dev    # http://localhost:3000
```

**Going live:** put a GitHub PAT + repo and a Linear API key in `.env`, set
`LLM_SOURCE=ollama` (and pull `nomic-embed-text` + a chat model on your Ollama
host). Then `--source live`, `engpulse rag-index` / `rag-search`, and
`engpulse ask "…" --source ollama`. Everything is the same code path — only the
config changes.

---

## Module map

| # | Module | What it does | Engineering judgement |
|---|---|---|---|
| 1 | **Foundations** | Typed config, normalized Postgres schema, one GitHub connector end-to-end | Model-agnostic LLM seam + replayable connectors from day one |
| 2 | **Ingestion & Normalization** | GitHub + CI + Linear connectors, incremental cursors + audit log, **entity resolution** (PR↔issue, GitHub↔Linear identity merge), labeled corpus | Cursors/audit as first-class tables; rule-based, confidence-scored, *measurable* resolution |
| 3 | **Metrics & Detectors** | PR-flow, CI/test-health (flaky), delivery/drift, scored vs labels | Deterministic, evidence-bearing flags; thresholds in YAML; eval live from the first detector |
| 4 | **Knowledge RAG + Synthesis** | Ownership/bus-factor, hybrid (vector+keyword) retrieval + rerank, grounded insight synthesis | Schema enforcement w/ retry-repair, hallucination check, abstention; facts ≠ inference |
| 5 | **Ask EngPulse agent** | Plan → call tools → multi-hop reason → cited answer / abstain / clarify | The agent reuses the same grounding contract; nothing it says is ungrounded |
| 6 | **Scoring + Alerts** | Transparent 0–100 health score + banding; role-routed, de-duplicated digests | No magic numbers (YAML); de-dup is the anti-noise mechanism |
| 7 | **API + Dashboard + Tracing** | FastAPI (+ SSE), Langfuse tracing on every LLM call, Next.js dashboard | DI sessions = offline-testable API; tracing is structural, not sprinkled |
| 8 | **Eval completion** | Consolidated report + determinism/regression guard | Same input → identical scores; the report is regenerable |

Detailed build log: [Docs/PROGRESS.md](Docs/PROGRESS.md).

## Key design decisions

1. **Fact / inference separation, enforced structurally.** Numbers and severities
   come from deterministic code; the model only contributes cited prose. A
   fabricated citation can't survive the grounding check.
2. **Offline-verifiable everything.** Every connector and LLM call has a
   live backend *and* a deterministic fake/fixture behind one protocol, so the
   entire system (including the agent and API) is testable with zero services —
   and the fixtures double as the eval corpus.
3. **Portable schema, real pgvector.** Core ORM uses portable types so the same
   metadata builds on SQLite (fast tests) and Postgres; the vector index lives in
   a separate pgvector-backed store so the core stays portable.
4. **Config over code.** Detector thresholds, scoring weights/bands, and alert
   routing all live in YAML — transparent and admin-tunable.
5. **Measured, not asserted.** A precision/recall harness scores detectors *and*
   the agent against a labeled set on every run, with a determinism guard.
6. **Model-agnostic seam.** Chat + embeddings are reached via base URL + model
   name (OpenAI-compatible), swappable to any provider via `.env`.

## CLI reference

```
# Data layer
check-config · init-db · ingest-github · ingest-linear · resolve · corpus-check
# Detectors & scoring
pr-flow · ci-health · delivery · knowledge · score · digest
# RAG & AI
rag-demo · rag-index · rag-search · synthesize · ask
# Evaluation
evaluate [--out json] [--report md]
```

## Project layout

```
engpulse/
  config.py · logging.py
  db/                  # normalized schema (PRD §9), engine/session
  connectors/github/   # async REST + fixture clients, DTOs, normalize
  connectors/linear/   # GraphQL + fixture clients
  ingest/              # cursors + audit, idempotent upserts, orchestrators
  resolve/             # PR↔issue linking + identity merge
  metrics/             # pr_flow · ci_health · delivery · knowledge + YAML thresholds
  scoring/             # 0–100 composite + banding (YAML)
  alerts/              # router + role-based digests (YAML)
  llm/                 # Ollama + fake chat/embeddings, tracing wrappers
  rag/                 # documents, chunking, vector stores, hybrid retriever
  synth/               # grounded synthesis (schema enforcement, abstention)
  agent/               # Ask EngPulse: planner, tools, agent loop
  obs/                 # pluggable tracer (no-op / recording / Langfuse)
  api/                 # FastAPI app, routes, deps, cache
  eval/                # labeled corpus loader, scorer, harness, report
config/                # thresholds.yaml · scoring.yaml · alerts.yaml
datasets/synthetic/    # labeled corpus (injected problems + labels.json)
frontend/              # Next.js role-based dashboard
tests/                 # 102 offline tests
```

## Tech stack

Python · FastAPI · SQLAlchemy 2 · PostgreSQL + pgvector · Pydantic · Typer · httpx ·
self-hosted **Ollama** (chat + embeddings, OpenAI-compatible) · Langfuse · Celery +
Redis · Next.js (React/TypeScript) · Docker Compose. Everything runs free and
self-hosted.

## Scope

**MVP (done):** GitHub + Actions + Linear ingestion, entity resolution, the four
detectors, ownership RAG, grounded synthesis, the Ask EngPulse agent, scoring,
alerts/digests, API + dashboard + tracing, and the eval harness.
**Phase 2:** Slack team-signal, tech-debt hotspot scorer, live webhooks, broader
corpus toward the 200-case target, richer dashboards.

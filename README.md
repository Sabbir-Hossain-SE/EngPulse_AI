# EngPulse AI — Engineering Org Intelligence Command Center

An agentic, RAG-powered operating layer that connects GitHub, CI/CD, and Linear to
surface delivery risk, review bottlenecks, flaky tests, knowledge silos, and
tech-debt hotspots — with grounded, evidence-cited insights and a natural-language
"Ask EngPulse" agent. Runs entirely on self-hosted open models; no data leaves your
network.

> **Build status:** Milestone 1 — *Foundations / Scaffold* ✅
> Repo structure, typed config, the normalized Postgres schema, and **one GitHub
> connector reading one repo end-to-end** are in place and verified.

---

## Core principle

Deterministic metrics are computed in code and are auditable; the language model
only **retrieves, reasons, prioritizes, and summarizes** — grounded in real records,
never inventing numbers. The scaffold establishes the deterministic spine the AI
layers will later hang off.

## The spine (this milestone)

```
GitHub API ──▶ connector (async, paginated, retrying)
                   │  typed DTOs (Pydantic)
                   ▼
              normalize (pure DTO → ORM)
                   │
                   ▼
          unified Postgres schema (pgvector enabled)
```

Everything else — metrics, detectors, RAG index, scoring, Ask EngPulse — reads from
and writes into this schema.

---

## Prerequisites

- Python **3.11+**
- Docker + Docker Compose (for Postgres/Redis/Langfuse)

## Setup

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

cp .env.example .env   # then fill in GITHUB_TOKEN and GITHUB_REPO for the live path
```

## Configuration

All configuration lives in one typed `Settings` object ([engpulse/config.py](engpulse/config.py)),
read from `.env`. Inspect the resolved config (secrets masked) any time:

```bash
engpulse check-config
```

The LLM is reached purely via `OLLAMA_BASE_URL` + model names (OpenAI-compatible),
so the provider is swappable with no code change. (No LLM is called in this
milestone — the seam is wired for later.)

---

## Verification

Three levels, fastest first. Levels 1–2 need **no services at all**.

### 1. Unit tests (offline)

```bash
pytest
```

Expected: `11 passed`. Covers config + secret-masking, the normalized schema and
its PR↔person links, and the full fixture → DTO → ORM read path (including
idempotency).

### 2. Offline read path (no DB, no GitHub)

Reads a recorded fixture, normalizes it, and prints a summary:

```bash
engpulse sync-repo --repo engpulse-demo/demo-repo --source fixture --dry-run
```

Expected output:

```
Sync summary — engpulse-demo/demo-repo
 Pull requests        3
 Distinct authors     2
 Distinct reviewers   3
 Persisted to DB      no (dry-run)
 Sample PR #s         101, 102, 103
```

### 3. Full spine into Postgres

```bash
docker compose up -d postgres        # or: docker-compose up -d postgres
engpulse init-db                     # enables pgvector + creates all tables
engpulse sync-repo --repo engpulse-demo/demo-repo --source fixture
```

Expected: `✓ Schema ready (10 tables) and pgvector extension enabled.` followed by
a summary showing **Persisted to DB: yes**. Re-running the sync is idempotent (no
duplicate rows).

### 4. Live GitHub read (your repo + PAT)

Put a `repo`-scoped token and target repo in `.env`, then:

```bash
engpulse sync-repo --source live --limit 20
```

### Full stack (optional)

```bash
docker compose up -d                 # Postgres+pgvector, Redis, Langfuse, API, worker
curl localhost:8000/health           # {"status":"ok",...}
```

> Langfuse and the worker are wired now but not exercised until the
> observability / ingestion milestones.

---

## Evaluation harness

Detectors are measured, not asserted. The harness runs the full pipeline
(ingest → resolve → detect) over a labeled synthetic corpus
([datasets/synthetic/](datasets/synthetic/)) and scores every detector and the
entity-resolution output against ground truth — on an ephemeral in-memory DB, so
it needs **no services**:

```bash
engpulse evaluate                 # prints per-task precision/recall/F1
engpulse evaluate --out eval.json # also writes a JSON report
```

| Task | Precision | Recall |
|---|---|---|
| stale_pr · flaky_test · deadline_drift | 1.00 | 1.00 |
| pr_issue_link · identity_merge | 1.00 | 1.00 |

> The corpus is a seed (a handful of deliberately injected cases); it grows toward
> the PRD's 200-case target. The point is the *measurement loop* — every detector
> is scored against labels, so quality can't silently regress.

---

## Project layout

```
engpulse/
  config.py                 # typed Settings (single source of config)
  logging.py                # structured logging
  db/
    base.py                 # engine, session_scope, declarative Base
    models.py               # unified normalized schema (PRD §9)
  connectors/github/
    schemas.py              # typed DTOs (connector boundary contract)
    client.py               # async REST client + fixture client (one protocol)
    normalize.py            # pure DTO → ORM mapping
  ingest/repo_sync.py       # end-to-end read path: fetch → normalize → upsert
  cli.py                    # check-config / init-db / sync-repo
  api/main.py               # FastAPI (/health, /readiness, /metrics)
  worker/celery_app.py      # Celery app (scheduled syncs land later)
migrations/                 # Alembic (wired; first autogen revision as schema grows)
tests/                      # offline unit tests + recorded GitHub fixtures
docker-compose.yml          # full-stack services
```

## Key design decisions

1. **Model-agnostic LLM seam from day one.** Ollama is reached only through a base
   URL + model name in config, so any OpenAI-compatible provider swaps in via `.env`.
2. **Schema-first, normalized, portable.** The §9 entities are defined up front with
   portable column types, so the same metadata builds on SQLite (fast offline tests)
   and Postgres (production), and `pgvector` is enabled from the start.
3. **Connector as a typed, replayable seam.** The reader depends on a `GitHubClient`
   protocol; a live REST client and a fixture client both satisfy it, so the
   end-to-end read path is verifiable offline and the fixtures seed the eval corpus
   later. Fetch (async) and persist (sync) are cleanly separated.

## Roadmap (PRD build order)

1. **Foundations / Scaffold** ✅ *(you are here)*
2. Ingestion & Normalization + entity resolution + test fixtures
3. Metrics & Detectors (PR-flow, CI/test-health, delivery-drift) + eval harness
4. Knowledge-silo RAG (index, hybrid search, reranking) + grounded synthesis
5. Ask EngPulse agent
6. Scoring engine + alert router + digests
7. API + dashboard + full tracing
8. Eval harness completion + README headline metrics

See [Docs/PROGRESS.md](Docs/PROGRESS.md) for the running build log.

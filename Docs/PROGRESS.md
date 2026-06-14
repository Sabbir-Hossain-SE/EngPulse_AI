# EngPulse AI — Build Progress

Running build log. One module at a time; each is verified before the next starts.

## Legend
- ✅ done & verified  ·  🔨 in progress  ·  ⬜ not started

---

## Module 1 — Foundations / Scaffold ✅

**What we built:** Repo structure, typed config system (model-agnostic Ollama
seam), the unified normalized Postgres schema (PRD §9) with pgvector enabled, a
FastAPI app + Celery worker, full-stack docker-compose, and **one GitHub connector
that reads one repo end-to-end** (repo metadata + PRs → normalized rows). The read
path is replayable from a recorded fixture so it verifies fully offline.

**Verify:**
```bash
pytest                                                                   # 11 passed
engpulse sync-repo --repo engpulse-demo/demo-repo --source fixture --dry-run   # offline, no services
docker compose up -d postgres && engpulse init-db && \
  engpulse sync-repo --repo engpulse-demo/demo-repo --source fixture     # full DB spine
```

**Verified output:** schema = 10 tables + pgvector; fixture sync persists 1 repo,
3 PRs, 3 people, 3 reviewer links; re-running is idempotent.

**Key files:** `engpulse/config.py`, `engpulse/db/models.py`,
`engpulse/connectors/github/`, `engpulse/ingest/repo_sync.py`, `engpulse/cli.py`.

---

## Module 2 — Ingestion & Normalization 🔨 (in progress)

Decisions: **live Linear** (connector supports live + offline fixtures) · sync =
**incremental cursors now, webhooks stubbed**.

### Sub-step 2.1 — GitHub + CI ingestion ✅

**What we built:** Extended the GitHub connector to commits, review events, and
GitHub Actions runs; added `head_sha` to PRs and a `pull_request_id` link on CI
runs (resolved by head SHA); added `SyncCursor` + `SyncAudit` tables with
incremental high-water-mark cursors and a per-resource audit log; reusable
idempotent upserts. New CLI: `ingest-github`.

**Verify:**
```bash
pytest                                                                       # 19 passed
engpulse ingest-github --repo engpulse-demo/demo-repo --source fixture --dry-run   # offline
docker compose up -d postgres && engpulse init-db && \
  engpulse ingest-github --repo engpulse-demo/demo-repo --source fixture     # full DB spine
```

**Verified output:** 12 tables; ingest persists 3 PRs / 4 commits / 4 CI runs
(3 linked to PRs) / 3 people / 2 bug-fix commits; cursors advance per resource;
audit rows all `ok`; re-run is idempotent.

### Sub-step 2.2 — Linear connector ✅

**What we built:** A GraphQL Linear connector (live + offline fixture, one
protocol) ingesting issues with status, estimate, due dates, assignee, labels,
and **transition history**. Normalization derives deterministic facts —
re-estimation history and deadline drift (original vs current due date) — from
that history. Linear assignees become `Person` rows keyed by tracker id + email
(`Person.email` added), staging the 2.3 cross-system merge. Extended the `Issue`
schema; added cursor + audit for the `issues` resource. New CLI: `ingest-linear`.

**Verify:**
```bash
pytest                                                                   # 26 passed
engpulse ingest-linear --source fixture --team ENG --dry-run             # offline
docker compose up -d postgres && engpulse init-db && \
  engpulse ingest-linear --source fixture --team ENG                     # full DB spine
```

**Verified output:** 3 issues / 2 assignees; ENG-101 shows deadline drift
(2026-06-05 → 2026-06-20) and 1 re-estimation; assignees keyed by tracker
id + email; re-run idempotent.

### Remaining sub-steps
- ⬜ **2.3 — Entity resolution**: PR↔Issue (branch/key/body) + cross-system
  identity merge (GitHub↔Linear by email), with a measurable resolution report.
- ⬜ **2.4 — Labeled fixtures**: synthetic corpus with injected problems + labels
  (eval seed).

> Per working agreement: checkpoint each sub-step before starting the next.

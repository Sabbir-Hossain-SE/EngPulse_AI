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

## What's next

⬜ **Module 2 — Ingestion & Normalization** (PRD §8.A): GitHub + CI + Linear
connectors, incremental sync with per-source cursors + webhooks, entity resolution
(PR↔issue↔person↔CI), audit log, and the labeled test fixtures. Extends the
connector and schema laid down here.

> Per working agreement: do not start Module 2 until Module 1 output is confirmed
> and the next module is explicitly approved.

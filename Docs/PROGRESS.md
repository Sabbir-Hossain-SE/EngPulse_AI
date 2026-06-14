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

## Module 2 — Ingestion & Normalization ✅ (complete)

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

### Sub-step 2.3 — Entity resolution ✅

**What we built:** Two deterministic, confidence-scored resolvers over the
ingested data. **PR↔Issue**: extract Linear keys from a PR's body (closing
keyword vs mention), branch ref, and title; link to the matching issue and
record method + confidence (only keys that exist as issues are linked, for
precision). **GitHub↔Linear identity merge**: collapse the separate Person rows
for one human, keyed by email, repointing every FK (author, reviewers, commits,
assignee). Connectors now create source-scoped people; the merge is the single
explicit resolution step (idempotent). New CLI: `engpulse resolve`; PRs gained
`head_ref`/`body`/`linked_issue_method`/`linked_issue_confidence`; commits carry
author email so GitHub people are mergeable.

**Verify:**
```bash
pytest                                                                   # 33 passed
docker compose up -d postgres && engpulse init-db && \
  engpulse ingest-github --repo engpulse-demo/demo-repo --source fixture && \
  engpulse ingest-linear --source fixture --team ENG && \
  engpulse resolve
```

**Verified output:** 3/3 PRs linked (branch / body_keyword / body_mention);
identities 5→3 (alice & bob each carry both GitHub + Linear ids, carol
untouched); FKs repointed (alice→2 issues, bob→1); re-run idempotent.

### Sub-step 2.4 — Labeled synthetic fixtures ✅

**What we built:** A synthetic corpus (`acme/payments`, `datasets/synthetic/`) in
the connector shapes with four **deliberately injected problems** — a stale
unreviewed PR, a flaky test (same SHA flips fail→pass), a deadline-drift issue
(due moved 3×), and a single-owner module — plus expected PR↔issue links and
identity merges in a `labels.json` ground-truth file. Typed loader
(`engpulse.eval`), a `validate_corpus` consistency check, and `corpus-check` CLI.
Ingest commands gained `--fixtures-dir` so the corpus runs through the real
pipeline. This is the eval-harness seed (PRD §13).

**Verify:**
```bash
pytest                                                                   # 37 passed
engpulse corpus-check                                                    # ✓ consistent
engpulse init-db && \
  engpulse ingest-github --repo acme/payments --source fixture --fixtures-dir datasets/synthetic && \
  engpulse ingest-linear --team PAY --source fixture --fixtures-dir datasets/synthetic && \
  engpulse resolve
```

**Verified output:** corpus is internally consistent; flows through ingest+resolve
reproducing every label — 3/3 PR links (branch / body_keyword / body_mention),
identities 6→4, PAY-12 drift 2026-05-15→2026-06-30.

---

## Module 3 — Metrics & Detectors ✅ (complete)

Deterministic signals (no LLM) over the linked graph; typed reports with
source-id evidence; thresholds in YAML; each detector scored against the
`datasets/synthetic` labels.

### Sub-step 3.1 — PR-Flow Analyzer (Module B) ✅

**What we built:** YAML-backed `Thresholds` (`config/thresholds.yaml`), a
precision/recall scorer (`engpulse.eval.prf`), and the PR-flow detector:
per-PR metrics (time-to-first-review, time-to-merge, size, rounds, reviewers)
and flags (stale / abandoned / unreviewed / oversized / merged-without-review /
review-bottleneck) → typed `PRFlowReport` with evidence. Reproducible via an
injectable `as_of`. New CLI: `engpulse pr-flow`.

**Verify:**
```bash
pytest                                                                   # 41 passed
engpulse init-db && \
  engpulse ingest-github --repo acme/payments --source fixture --fixtures-dir datasets/synthetic && \
  engpulse pr-flow --repo acme/payments --as-of 2026-06-14
```

**Verified output:** PR#1 flagged abandoned+unreviewed (the labeled stale PR);
stale-PR detection scores **precision 1.0 / recall 1.0** against the corpus.

### Sub-step 3.2 — CI/Test-Health Detector (Module C) ✅

**What we built:** Flaky-test detection (a test that fails then passes on the
*same commit SHA*, ranked by flip rate), failure clustering (by failing-test
signature), and per-workflow duration trends with regression flags → typed
`CIHealthReport`, each finding grounded in CI run ids. Ingestion now persists
`failed_tests` (CIRunDTO → CIRun). New CLI: `engpulse ci-health`.

**Verify:**
```bash
pytest                                                                   # 45 passed
engpulse init-db && \
  engpulse ingest-github --repo acme/payments --source fixture --fixtures-dir datasets/synthetic && \
  engpulse ci-health --repo acme/payments
```

**Verified output:** `test_checkout_timeout` flagged flaky on `f1aky00sha`
(flip rate 0.5, runs 991000001/991000002); flaky detection scores
**precision 1.0 / recall 1.0** vs the corpus.

### Sub-step 3.3 — Delivery & Deadline-Drift Analyzer (Module D) ✅

**What we built:** Issue cycle time, stale-issue detection, **deadline drift**
(due-date moves from transition history), re-estimation, WIP-per-assignee, and
the accountability gap **done-without-merged-PR** → typed `DeliveryReport` with
issue-key + transition evidence. Ingestion now captures the Linear `createdAt`
(`source_created_at`) for cycle time. New CLI: `engpulse delivery`.

**Verify:**
```bash
pytest                                                                   # 50 passed
engpulse init-db && \
  engpulse ingest-github --repo acme/payments --source fixture --fixtures-dir datasets/synthetic && \
  engpulse ingest-linear --team PAY --source fixture --fixtures-dir datasets/synthetic && \
  engpulse resolve && engpulse delivery --team PAY --as-of 2026-06-14
```

**Verified output:** PAY-12 flagged deadline_drift (3 moves, 2026-05-15→2026-06-30)
+ stale + re-estimation; PAY-20 flagged done_without_merged_pr (linked PR open).
Drift detection scores **precision 1.0 / recall 1.0** vs the corpus.

### Sub-step 3.4 — Consolidated eval harness ✅

**What we built:** `engpulse.eval.run_evaluation` runs the full pipeline
(ingest → resolve → detect) over the labeled corpus on an **ephemeral in-memory
DB** (no services) and scores all five tasks against ground truth via the
precision/recall scorer. New CLI: `engpulse evaluate [--out report.json]`.
README now carries the headline metrics.

**Verify:**
```bash
pytest              # 53 passed
engpulse evaluate   # no services needed
```

**Verified output:** stale_pr, flaky_test, deadline_drift, pr_issue_link,
identity_merge — all **precision 1.0 / recall 1.0**; macro 1.00/1.00.

---

## What's next

⬜ **Module 4 — Knowledge-Silo RAG + Grounded Synthesis** (PRD §8.E/I,
Milestone 4): ownership graph + bus-factor from commit/blame history, hybrid
(vector + keyword) index over code/PR/issue text in pgvector with reranking, and
grounded insight synthesis with schema enforcement + faithfulness checks. First
module to use the Ollama LLM seam wired in Module 1.

> Per working agreement: checkpoint each sub-step before starting the next.

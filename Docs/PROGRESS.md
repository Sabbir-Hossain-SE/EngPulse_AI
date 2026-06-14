# EngPulse AI — Build Progress

Running build log. One module at a time; each is verified before the next starts.

## Legend

- ✅ done & verified · 🔨 in progress · ⬜ not started

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
_same commit SHA_, ranked by flip rate), failure clustering (by failing-test
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

- stale + re-estimation; PAY-20 flagged done_without_merged_pr (linked PR open).
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

## Module 4 — Knowledge-Silo RAG + Grounded Synthesis ✅ (complete)

### Sub-step 4.1 — Ownership graph + bus-factor (Module E, deterministic) ✅

**What we built:** Ownership map from commit→file history (`files` now ingested
on commits; `Commit.author` relationship added) and a single-point-of-failure
detector — a module owned by ≤N contributors _with real churn_ → typed
`KnowledgeRiskReport` with owner/commit evidence. New CLI: `engpulse knowledge`.
Bus-factor added to the eval harness (now **6 labeled tasks**).

**Verify:**

```bash
pytest                                                                   # 55 passed
engpulse evaluate                                                        # 6 tasks, macro 1.00/1.00
engpulse init-db && \
  engpulse ingest-github --repo acme/payments --source fixture --fixtures-dir datasets/synthetic && \
  engpulse knowledge --repo acme/payments
```

**Verified output:** `auth/tokens.py` flagged SPOF (dave, 3 commits); the other
single-owner files (1 commit each) correctly _not_ flagged. bus_factor eval
**precision 1.0 / recall 1.0**.

Decisions: **live Ollama** (real `OllamaEmbeddingClient` + deterministic
`FakeEmbeddingClient` so tests stay offline) · **pluggable light reranker**
(lexical default, cross-encoder swappable).

### Sub-step 4.2 — RAG core ✅

**What we built:** Model-agnostic embeddings (`engpulse.llm`: Ollama +
deterministic fake), document builder (PR/issue/commit + synthesized ownership
docs), chunking, a `VectorStore` (in-memory for tests/offline · `PgVectorStore`
for prod), and a `HybridRetriever` — dense + keyword fused by RRF, then a
pluggable `LexicalReranker`. Every chunk keeps its source ref for citation. New
CLI: `rag-demo` (offline) · `rag-index` / `rag-search` (live Ollama + pgvector).

**Verify (offline, no services):**

```bash
pytest                                                                   # 62 passed
engpulse rag-demo --query "who owns the auth tokens module"   # → auth/tokens.py top
engpulse rag-demo --query "PAY-20 checkout"                   # → issue PAY-20 (keyword)
```

**Verify live (your Ollama + Postgres):**

```bash
engpulse init-db && engpulse ingest-github --repo acme/payments --source fixture --fixtures-dir datasets/synthetic
engpulse rag-index  --repo acme/payments                      # embeds via Ollama into pgvector
engpulse rag-search --repo acme/payments --query "who owns auth tokens"
```

**Verified output (offline):** semantic query ranks the `auth/tokens.py`
ownership doc #1; exact key `PAY-20` retrieved via keyword; retrieval
deterministic.

### Sub-step 4.3 — Grounded synthesis (Module I) ✅

**What we built:** The Ollama _chat_ client (`engpulse.llm.chat`: live +
`Scripted`/`Fake` for tests) and the grounded-synthesis pipeline
(`engpulse.synth`): a strict grounding contract, **schema enforcement with
retry/repair** (`generate_structured`), a **hallucination check** that drops any
claim whose cited refs aren't in the evidence, and **abstention** on thin/
ungrounded evidence. Severity + numbers stay deterministic; the model only writes
cited prose. New CLI: `engpulse synthesize` (`--source fake|ollama`).

**Verify (offline):**

```bash
pytest               # 69 passed
engpulse synthesize  # SPOF on auth/tokens.py → grounded insight, severity from the flag
```

Live chat: `engpulse synthesize --source ollama` (uses your chat model for the prose).

**Verified output:** `single_point_of_failure on auth/tokens.py`, severity
**high** (from the flag), not abstained, confidence 0.80, citations
`auth1sh, metric:auth/tokens.py` — no hallucinated claims.

---

## Module 5 — Ask EngPulse agent ✅ (complete)

### Sub-step 5.1 — Agent core ✅

**What we built:** A tool registry (`retrieval`, `ownership`, `delivery`,
`ci_health`, `pr_flow`) each returning citable evidence; a pluggable planner
(`RuleBasedPlanner` default + `LLMPlanner`); and the `AskAgent` loop —
plan → call tools (multi-hop) → assemble deduped evidence → grounded cited
answer (reuses 4.3's schema enforcement + grounding), with **abstention** (no
evidence / all claims ungrounded) and a **clarifying question** for vague input.
`generate_structured` is now schema-generic. New CLI: `engpulse ask`.

**Verify (offline):**
```bash
pytest                                                  # 76 passed
engpulse ask "who owns the auth tokens module and what is at risk"
engpulse ask "what is the meaning of life"              # → abstains
engpulse ask "what about it?"                           # → clarifying question
```
Live: `engpulse ask "..." --source ollama --planner llm`.

**Verified output:** ownership question → multi-hop plan, cited answer
(`metric:auth/tokens.py`, …); unanswerable → abstains; vague → clarifies.

### Sub-step 5.2 — Agent eval (PRD §13) ✅

**What we built:** A labeled question set in the corpus (`agent_questions`:
answerable + unanswerable) and `evaluate_agent` scoring **source recall**,
**citation faithfulness**, and **correct-abstention rate**, surfaced in
`engpulse evaluate` and the JSON report.

**Verify:**
```bash
pytest             # 79 passed
engpulse evaluate  # agent: recall/faithfulness/abstention all 1.00
```

**Verified output:** 3/5 answerable; source recall 1.00, citation faithfulness
1.00, correct abstention 1.00 — alongside the 6 detector tasks at 1.0/1.0.

---

## Module 6 — Scoring + Alerts + Digests ✅ (complete)

### Sub-step 6.1 — Scoring engine (Module H) ✅

**What we built:** A transparent, YAML-driven health model
(`config/scoring.yaml` → typed `ScoringConfig`): each sub-score (review_flow,
delivery, ci_test, knowledge) starts at 100 and loses points per flag by
severity; composite = weighted average → status band (Healthy/Watch/At Risk/
Critical). Every score decomposes to its contributing flags; persisted as a
`Score` row with delta + denormalized onto the repo. New CLI: `engpulse score`.

**Verify:**
```bash
pytest                                                  # 83 passed
engpulse init-db && ...ingest... && engpulse resolve && \
  engpulse score --repo acme/payments --team PAY --as-of 2026-06-14 --persist
```

**Verified output:** review_flow 75 · delivery 45 · ci_test 90 · knowledge 80 →
composite **70.0 = At Risk**, persisted with breakdown + delta.

### Sub-step 6.2 — Alert router + role-based digests (Module K) ✅

**What we built:** A YAML-driven router (`config/alerts.yaml`) mapping detector
flags → severity-classified alert types → recipient roles (EM/TL/PM/IC), with
**de-duplication** (one alert per subject+type, merging reasons + escalating to
max severity), **suppression** below a configurable floor, and a project
health-drop alert. Role-filtered daily/weekly digests carrying
evidence/confidence/action/owner. New CLI: `engpulse digest`.

**Verify:**
```bash
pytest                                                  # 88 passed
engpulse init-db && ...ingest... && engpulse resolve && \
  engpulse digest --repo acme/payments --role EM --team PAY --as-of 2026-06-14
```

**Verified output:** EM digest = delivery_risk PAY-12 (3 flags de-duped) +
knowledge_risk auth/tokens.py + project health-drop; TL digest = the flaky test;
IC digest = the stalled-PR/issue execution items.

---

## Module 7 — API, Dashboard & Observability ✅ (complete)

### Sub-step 7.1 — API core ✅

**What we built:** FastAPI endpoints surfacing Modules 1–6 — `GET /projects`,
`/score`, `/alerts`, `/digest`, `/knowledge` and `POST /ask` (Ask EngPulse) plus
`/health` `/readiness` `/metrics`. DB sessions are dependency-injected (tests
override to the ephemeral corpus DB), an in-memory TTL cache backs the retriever,
and the LLM backend is config-driven (`LLM_SOURCE=fake` default → runs offline).

**Verify (offline):**
```bash
pytest                                                  # 96 passed
# live: DATABASE_URL=... uvicorn engpulse.api.main:app
#   GET /score?repo=acme/payments&team=PAY&as_of=2026-06-14   → 70.0 At Risk
#   POST /ask {"question":"who owns the auth tokens module", ...}
```

**Verified output:** TestClient covers every endpoint over the corpus; a live
uvicorn run returned score 70.0/At Risk and a grounded `/ask` answer citing
`metric:auth/tokens.py` (and abstained on the unanswerable question).

### Sub-step 7.2 — Observability + streaming ✅

**What we built:** A pluggable tracer (`engpulse.obs`: `NoOpTracer` default ·
`RecordingTracer` for tests · best-effort `LangfuseTracer`) with a
`span(name, **meta)` context manager; `Traced{Chat,Embedding}Client` wrappers so
the factories emit a span on **every** LLM call; and `agent.ask_events` — a
traced generator that streams reasoning stages, exposed at `POST /ask/stream` as
**Server-Sent Events**.

**Verify (offline):**
```bash
pytest   # 99 passed
# /ask/stream emits: event: plan → tool → answer → final
# RecordingTracer captures llm.embed, llm.chat, tool.*, agent.ask — no silent calls
```

**Verified output:** SSE stream shows plan→tool→answer→final; trace spans cover
every embed + chat call plus tool/agent spans. Langfuse auto-activates when
`LANGFUSE_PUBLIC_KEY`/`SECRET_KEY` are set (else no-op).

### Sub-step 7.3 — Dashboard (React/Next.js) ✅

**What we built:** A role-based Next.js (App Router, TypeScript) dashboard in
`frontend/` over the API — health score + breakdown, role-filtered alerts/digest,
ownership / bus-factor map, and a **streaming Ask EngPulse box** (consumes
`/ask/stream` SSE via fetch + ReadableStream). API gained CORS for the dashboard
origin. Typed API client; minimal-deps (next/react only).

**Verify:**
```bash
# API
uvicorn engpulse.api.main:app --port 8000
# dashboard
cd frontend && npm install && npm run build   # ✓ compiles + type-checks
npm run dev                                    # http://localhost:3000
```

**Verified output:** `next build` compiles cleanly (types valid, static pages
generated); `next start` serves HTTP 200 with the EngPulse shell. (Browser UI
not visually verified in this environment; it's wired to the tested API.)

---

## What's next

⬜ **Module 8 — Eval harness completion + README** (PRD §13, Milestone 6):
broaden the labeled corpus toward the headline targets, finalize the eval report,
and write the README with the headline metrics + design-decision write-up that
make the build read as senior. The measurement loop already exists (Module 3.4 /
5.2) — this widens coverage and packages it.

> Per working agreement: checkpoint each sub-step before starting the next.

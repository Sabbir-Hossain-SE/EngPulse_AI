# Datasets

## `synthetic/` — labeled evaluation corpus

A small, fully synthetic engineering corpus (`acme/payments`) in the exact shapes
the connectors produce, with **deliberately injected problems** and a
`labels.json` ground-truth file. It is the seed for the evaluation harness: the
detectors (Module 3) and the entity-resolution accuracy metrics are scored
against these labels.

### Injected problems (ground truth in `labels.json`)

| Problem | Where | Label |
|---|---|---|
| **Stale PR** | PR #1, open since 2026-05-01 with no review | `stale_prs` |
| **Flaky test** | `test_checkout_timeout` fails then passes on SHA `f1aky00sha` | `flaky_tests` |
| **Deadline drift** | `PAY-12` due date moved 3× (2026-05-15 → 2026-06-30) | `deadline_drifts` |
| **Single-owner module** | `auth/tokens.py` touched only by `dave` | `bus_factors` |
| **PR↔Issue links** | PR1→PAY-12 (branch), PR2→PAY-20 (keyword), PR3→PAY-21 (mention) | `pr_issue_links` |
| **Identity merges** | `dave` and `erin` across GitHub + Linear (by email) | `identities` |

### Use it

```bash
# Validate the corpus is internally consistent (every label points at a real entity)
engpulse corpus-check

# Run it through the real pipeline against a DB
engpulse init-db
engpulse ingest-github --repo acme/payments --source fixture --fixtures-dir datasets/synthetic
engpulse ingest-linear --team PAY --source fixture --fixtures-dir datasets/synthetic
engpulse resolve
```

The files mirror the connector fixtures: `github_repo.json`, `github_prs.json`,
`github_reviews.json`, `github_commits.json` (with `files` for ownership),
`github_runs.json` (with `failed_tests` for flaky detection), `linear_issues.json`,
and the `labels.json` ground truth.

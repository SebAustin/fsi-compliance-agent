# Assumptions — agency enhancement pass (branch `agency/hybrid-retrieval`)

Input: "review the project and enhance if needed" on an existing, healthy repo
(`fsi-compliance-agent`). Baseline at intake: 80 tests passing, ~88% coverage,
`ruff` + `mypy --strict` clean, CI green, all 3 original issues closed.

## Scope of this pass
Driven by `codebase-analyst` findings. **In scope** (coherent, low-risk, high-value):

1. **Hybrid retrieval (issue #4)** — the one substantive open item. Add dense+lexical
   fusion (RRF) in `RulebookIndexer.search()` to close the documented PEP recall gap,
   without changing the public signature or the offline fallback.
2. **Examiner-report label fix** — `audit/report.py` renders `sanctions_screening` raw;
   add it to `_NODE_LABELS` (visible in the examiner artifact, which is "the product").
3. **Determination JSON parse hardening** — `_parse_decision_json` takes the *first*
   match; use the *last* so a stray earlier JSON block can't flip the decision.
4. **Audit append perf** — cache the last hash in memory instead of re-reading the whole
   JSONL on every `record()`.

## Explicitly deferred (documented, not done this pass)
- **Multi-worker approval store** — `approval_gate` keeps pending approvals in-process
  dicts. Correct for the single-process MVP; horizontal scaling needs Redis/Postgres.
  Out of scope (needs infra); noted as a known limitation.
- **Eval judge concurrency** — `run_eval` runs judge calls serially; an eval-only speed
  optimization, not correctness. Deferred unless cheap.

## Guardrails honored
- Work on feature branch `agency/hybrid-retrieval`, never `main`.
- No regressions: existing tests must stay green.
- No real secrets; synthetic data only.
- Live re-index + held-out eval will be run to validate the retrieval change (uses the
  user's existing OpenAI key in `.env` and local Qdrant — read-only spend, already in use).

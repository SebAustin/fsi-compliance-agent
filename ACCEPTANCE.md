# Acceptance — agency enhancement pass

Branch `agency/hybrid-retrieval` (committed; not merged to `main`). Input: "review the
project and enhance if needed." Verdict from `solution-verifier`: **SOLID (5.00/5.00)**.

## Per success criterion (PLAN.md, as revised r2)

| # | Criterion | Result | Evidence |
|---|---|---|---|
| 1 | Hybrid retrieval delivers a deterministic recall improvement; h-012 OOD gap left un-tuned and safe | **PASS** | `test_hybrid_surfaces_pep_rule_when_dense_misses_it`; live lift of AML-004 for "senior government official"; h-012 escalates to human (no FN) |
| 2 | False-negative rate 0.00 on calibration (100) and held-out (28) | **PASS** | calib + held-out eval = 0.00 / 0.00 |
| 3 | No calibration regression (FN 0.00, accuracy 1.00, citation 1.00) | **PASS** | calibration re-validated post-fix |
| 4 | 80 existing + new tests green; ruff + mypy --strict clean; coverage ≥85% | **PASS** | 97 passed, 88.9% coverage, lint/type clean |
| 5 | Invariants preserved (search() signature, offline fallback, sanctions injection, audit tamper detection) | **PASS** | targeted tests pass; `verify()` reads disk |

## Built this pass
- **Hybrid retrieval** (RRF dense+lexical) — `rulebook/indexer.py`.
- **Sanctions-ownership correctness fix** — AML-036 + flag-dominance: sub-threshold
  sanctioned ownership is non-clearable (fixed false negative c-071 found mid-build).
- **Examiner-report label**, **last-match decision parse**, **cached audit last-hash**.
- **Eval `citation_coverage`** redefined to the contract's population (compliant/flag).
- Deliverables: `CODEBASE.md`, `PLAN.md`, `ASSUMPTIONS.md`, `SECURITY.md` (STRIDE), 17
  new tests.

## Measured (live, OpenAI gpt-4.1)
| Set | FN rate | Accuracy | Citation | Abstention |
|---|---|---|---|---|
| Calibration (100) | 0.00 | 1.00 | 1.00 | ~3% |
| Held-out (28) | 0.00 | 1.00 | 1.00 | ~11% (was ~14%) |

## Deferred / tracked (not done this pass)
- **Issue #4** — fully closing the "foreign finance minister" PEP recall gap needs query
  expansion / LLM query rewriting (hybrid retrieval narrowed but did not close it; the
  case stays safe). Deliberately not tuned to the held-out case.
- **Issue #5** — pre-existing High: the HTTP API (`/review`, `/approvals/{id}`) is
  unauthenticated (the non-Slack path can bypass the HITL gate). Out of scope for a
  retrieval pass; adding authN is a separate feature requiring an explicit go.
- Multi-worker approval store (in-process dicts) — needs Redis/Postgres before scaling.

## Notes
- Work is committed on the feature branch only. Merging to `main` / pushing to the
  remote is left for an explicit go (agency guardrail).
- Live-eval JSON artifacts were generated against the working tree immediately before the
  final commit; the committed bytes match, and the 97 deterministic tests run against the
  committed code.

---

## Addendum — architecture diagram pass (branch `agency/arch-diagram`)

Input: "enhance the readme with a high quality architecture diagram." Docs-only.

- Replaced the basic README flowchart with two styled, GitHub-native Mermaid diagrams: a
  color-coded layered architecture (ingress → LangGraph pipeline → external services /
  rulebook controls → cross-cutting hash-chained audit) with the four contracts mapped onto
  the graph, plus a sequence diagram for the high-risk HITL approval lifecycle.
- Verified: Mermaid parses/renders with the live engine (same as GitHub); 5 subgraphs / 5
  ends balanced; all class references defined. No code touched — 97 tests remain green.

---

## Addendum — diagram visual polish (branch `agency/pretty-diagrams`)

Input: "make the diagrams more attractive." Docs-only.

- Replaced the default-themed Mermaid with two bespoke hand-designed SVGs in `docs/img/`
  (`architecture.svg`, `hitl-sequence.svg`): cohesive 5-color palette, soft depth, rounded
  cards, drawn audit padlock, legend mapping colors → the four contracts, numbered HITL
  swimlane with fail-safe callouts. Embedded via `<img>` (GitHub renders committed SVGs).
- Verified: both SVGs well-formed XML and rendered with the live SVG engine before commit;
  long crossing connectors removed for clarity. No code touched — 97 tests green.

# Architecture

`fsi-compliance-agent` is a LangGraph `StateGraph` over a typed `CaseState`. Each node
is a pure-ish async function `CaseState -> CaseState` (it returns a new state copy; it
does not mutate the input). External effects — LLM calls, embeddings, Slack, the audit
log — are isolated behind small functions so every network boundary is mockable and the
graph runs offline in tests and local dev.

## The graph

```
START
  -> triage            (Haiku 4.5)   case_type + risk_tier
  -> rule_retrieval    (Qdrant/voyage, token-overlap fallback)  retrieved_rules
  -> determination     (Sonnet 4.6 + Citations API)  Determination
  -> abstain           (conformal)   abstained?, approval_required?
  -> { human_review (END) | approval_gate -> close | close }
  -> END
```

The conditional edge after `abstain` is the heart of the routing:

| condition | route | rationale |
|---|---|---|
| `abstained` | `human_review` (END) | confidence below the calibrated τ — hand to a human, do not guess |
| `risk_tier == high` and `decision == flag` | `approval_gate` -> `close` | high-risk flags never auto-close |
| otherwise | `close` | auto-close with a citation trail |

## The four contracts

The design is organized around four hard contracts, enforced in code rather than left to
prompt discipline:

1. **Citation contract** (`nodes/determination.py`) — a `compliant`/`flag` decision with
   zero citations raises `CitationContractError`. You cannot clear or flag a transaction
   on an uncited basis.
2. **Abstention contract** (`nodes/abstain.py`, `scripts/calibrate.py`) — confidence is
   turned into a conformal nonconformity score; above the calibrated threshold (alpha=0.05)
   the agent abstains to human review.
3. **Approval-gate contract** (`nodes/approval_gate.py`) — high-risk flags block on a
   Slack HITL decision; on timeout the case stays `pending` (fail safe toward review).
4. **Audit contract** (`audit/log.py`) — every closed case appends to a hash-chained,
   append-only log; `verify()` detects any tampering.

## Failure posture

Every defaulting decision is biased toward *more* scrutiny, never less: an unknown risk
tier escalates to `high`, an unreachable approval gate stays `pending`, an uncited
determination is rejected outright. In a cost-asymmetric domain, the safe default is the
one that costs an analyst time, not the one that misses a flag.

## Models (pinned Jun 2026)

| Stage | Model | Why |
|---|---|---|
| Triage | Haiku 4.5 | cheap, high-volume classification |
| Determination | Sonnet 4.6 | best reasoning + Citations API |
| Eval judge | Opus 4.7 | independent, highest-reasoning grader |
| Embeddings | voyage-3-large (dim 256) | rule-clause retrieval |

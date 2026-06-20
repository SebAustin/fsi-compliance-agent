# fsi-compliance-agent — Codebase Map

## Overview

A LangGraph pipeline that runs financial AML/compliance cases through a deterministic
multi-node review process: triage, rule retrieval, sanctions screening, LLM determination,
conformal abstention, Slack HITL approval gate, and close. Every decision is citation-grounded;
uncited compliant/flag determinations are contractually rejected, not silently emitted.

---

## Stack

| Layer | Choice | Version |
|-------|--------|---------|
| Language | Python | 3.12 (pinned) |
| Orchestration | LangGraph | 1.0.3 |
| LLM (determination) | Anthropic Sonnet 4.6 (Citations API) / OpenAI gpt-4.1 | anthropic 0.41.0, openai 2.41.1 |
| LLM (triage) | Haiku 4.5 / gpt-4.1-mini | same clients |
| LLM (eval judge) | Opus 4.7 / gpt-4.1 | same clients |
| Embeddings | Voyage voyage-3-large / OpenAI text-embedding-3-large, dim=256 | voyageai 0.3.2 |
| Vector store | Qdrant (local Docker or remote) | qdrant-client 1.12.1 |
| Validation | Pydantic v2 | 2.9.2 |
| Config | pydantic-settings (.env) | 2.6.1 |
| HTTP API | FastAPI + uvicorn | 0.115.6 / 0.32.0 |
| Logging | structlog | 24.4.0 |
| HITL notifications | Slack SDK | 3.33.4 |
| Calibration math | numpy + scipy | 2.1.3 / 1.14.1 |
| Package manager | uv | — |
| Linter | ruff (ALL rules, select ignores) | 0.8.4 |
| Type checker | mypy --strict | 1.13.0 |
| Test runner | pytest + pytest-asyncio + pytest-cov | 8.3.4 |

---

## Build / Run / Test

```bash
uv sync --all-extras            # install (make install)

# external services (optional — tests run fully offline without them)
make qdrant                     # docker compose up qdrant, waits for ready
make index                      # embed 46 rules into Qdrant (uv run python -m scripts.build_index)
make calibrate                  # fit abstention tau on evals/cases.jsonl

# run
make serve                      # uvicorn on :8000
make review CASE="your case text"

# quality gates
make lint                       # ruff check + format --check
make type                       # mypy --strict src/
make test                       # pytest, --cov-fail-under=85 (actual: ~88%)
make ci                         # lint + type + test (all three)

# evals (require API keys)
make eval                       # 100-case calibration set
make eval-holdout               # 28-case held-out OOD set
make eval-smoke                 # 15-case CI smoke subset
```

---

## Directory Map

```
src/compliance_agent/
├── config.py              Settings (pydantic-settings), calibrated_threshold()
├── state.py               CaseState TypedDict; CitedRule, Determination, RetrievedRule Pydantic models
├── graph.py               build_graph() — StateGraph wiring, routing logic
├── providers.py           OpenAI / Anthropic dispatch (chat sync/async, embed_texts), cost tracking
├── sanctions.py           Deterministic watchlist screening (exact + fuzzy Jaccard)
├── slack.py               Slack signature verification, interaction payload parsing
├── nodes/
│   ├── triage.py          triage_node — Haiku/mini classifies case_type + risk_tier
│   ├── rule_retrieval.py  rule_retrieval_node — calls RulebookIndexer.search()
│   ├── sanctions_screening.py  sanctions_screening_node — screen_text + _ensure_sanctions_rules
│   ├── determination.py   determination_node — Anthropic Citations API or OpenAI quote-verify
│   ├── abstain.py         abstain_node — conformal nonconformity check (1-confidence > tau)
│   ├── approval_gate.py   approval_gate_node — Slack HITL, asyncio.Event wait
│   ├── close.py           close_node — honors override, writes final audit entry
│   └── exceptions.py      CitationContractError, ApprovalGateError
├── rulebook/
│   ├── indexer.py         RulebookIndexer.build() + search() — vector search + token-overlap fallback
│   ├── rules.jsonl        46 synthetic AML rule clauses (AML-001 … AML-046)
│   └── watchlist.jsonl    16 synthetic SDN watchlist entries
├── audit/
│   ├── log.py             AuditLog — hash-chained append-only JSONL, verify()
│   ├── recorder.py        record() — thin convenience wrapper over AuditLog.append()
│   └── report.py          render_case_report() — Markdown examiner export
└── api/
    └── server.py          FastAPI app: POST /review, POST/GET /approvals, /audit/*, /slack/interactivity

evals/
├── cases.jsonl            100 labeled calibration cases
├── holdout.jsonl          28 labeled held-out OOD cases
├── judge.py               judge_determination() — LLM quality scorer [0,1]
└── run_eval.py            typer CLI; gates on FN rate ≤ 0.03 and citation coverage ≥ 0.99

scripts/
├── build_index.py         uv run python -m scripts.build_index
├── calibrate.py           split-conformal tau fitting (alpha=0.05)
└── review.py              single-case review CLI

tests/
├── conftest.py            settings fixture (monkeypatched, all API keys cleared → fully offline)
├── test_retrieval.py      RulebookIndexer unit tests — offline fallback is exercised here
├── test_sanctions.py      screen_text + sanctions_screening_node
├── test_determination.py  determination_node with mocked _determine_llm
├── test_abstain.py        conformal logic
├── test_approval_gate.py  asyncio gate resolution
├── test_graph.py          end-to-end with mocked LLM + indexer
└── test_holdout.py        structural integrity of evals/holdout.jsonl
```

---

## Architecture and Data Flow

```
POST /review
    └─> graph.ainvoke({case_id, case_text})
            |
        triage_node          [Haiku/mini] → {case_type, risk_tier}
            |
        rule_retrieval_node  → RulebookIndexer.search(case_text, top_k=8)
            |                    tries _vector_search (Qdrant + embed)
            |                    on any exception → _local_search (Jaccard token overlap)
            |
        sanctions_screening_node  → screen_text(case_text, watchlist)
            |                         on hit: _ensure_sanctions_rules(retrieved_rules)
            |                                  injects AML-046, AML-007
            |                         exact hit: forces risk_tier="high"
            |
        determination_node   [Sonnet Citations API or gpt-4.1 quote-verify]
            |                   raises CitationContractError → graph catches → escalate
            |
        abstain_node         nonconformity = 1 - confidence
            |                if > tau (calibrated) → abstained=True
            |                if high+flag → approval_required=True
            |
        _route_after_abstain ──────────────────────────────────────┐
            ├─ abstained=True  ──→ END (human review)              │
            ├─ approval_required ──→ approval_gate_node            │
            │                        Slack HITL; asyncio.Event wait │
            │                        → close_node                   │
            └─ else  ──→ close_node ────────────────────────────────┘
                             final_decision honors override
                             appends hash-chained audit entry
```

Trust boundary: everything before `determination_node` is deterministic or fast-model. The
Anthropic/OpenAI call is the only external write-capable trust boundary; it is mocked in all
unit tests. Slack HITL is the only human-input boundary; it is signature-verified and
auto-approved in evals.

---

## Four Enforced Contracts

| Contract | Where enforced |
|----------|---------------|
| **Citation** | `determination_node`: `compliant`/`flag` with zero citations raises `CitationContractError`; graph escalates to human rather than auto-deciding. OpenAI path verifies quoted spans against clause text with `_verify_citations`. |
| **Abstention** | `abstain_node`: split-conformal nonconformity > calibrated tau → human queue. Tau fitted at alpha=0.05 on calibration set via `scripts/calibrate.py`. |
| **Approval gate** | `approval_gate_node`: `risk_tier=high` + `decision=flag` never auto-closes; waits on Slack HITL `asyncio.Event`; timeout leaves status "pending" (fails safe). |
| **Audit** | `audit/log.py`: every node transition appended with SHA-256 hash chain. `verify()` detects tampering, reordering, or deletion. `GET /audit/case/{id}` renders Markdown examiner report. |

---

## Conventions

- **Ruff**: `select = ["ALL"]` with narrow ignores (D, COM812, ISC001, EM101/102, TRY003, TC001-3). `line-length = 100`. Per-file ignores relax `S101`, `ANN`, `T201` for tests/evals/scripts.
- **mypy**: `--strict`, `python_version = "3.12"`, `pydantic.mypy` plugin.
- **Immutability**: all state transitions via `{**state, ...}` spread. Pydantic models are `frozen=True, extra="forbid"`.
- **Logging**: structlog throughout; every node logs its transition with `case_id`.
- **No hardcoded thresholds at call sites**: all config via `Settings`; calibrated tau via `.calibration.json`.
- **Module-level singletons**: `_indexer` (rule_retrieval.py) and `_watchlist` (sanctions_screening.py) are process-wide caches loaded once.
- **Commit types**: feat / fix / refactor / docs / test / chore / perf / ci.
- **Provider abstraction**: `providers.py` dispatches on `settings.llm_provider` / `settings.embed_provider`; nodes never import `openai` or `anthropic` directly except in `determination.py` and `providers.py`.

---

## Tests

- **80 tests, 88% coverage** (threshold 85%). All run offline — every network boundary is mocked.
- `conftest.py` clears the `get_settings()` LRU cache and zeros all API keys for each test.
- Coverage gaps: `providers.py` at 35% (network paths never called in unit tests — acceptable), `rulebook/indexer.py` at 71% (Qdrant paths exercised only integration-side).
- No integration tests against live Qdrant or LLM APIs in the test suite; those paths are covered by `make eval`.
- Eval gates: false-negative rate ≤ 0.03, citation coverage ≥ 0.99. Latest run (sha 1c3ad8d, 100 cases): FN=0.00, citation=1.00, accuracy=1.00, abstention=0.05.

---

## Dependencies and Risk

- `langgraph==1.0.3` — pinned; LangGraph has had breaking API changes across minor versions.
- `anthropic==0.41.0` — Citations API is used but is still in beta; field names (`start_char_index`, `end_char_index`, `document_index`) may drift. See `determination.py:203-215`.
- `voyageai==0.3.2` — client interface differs from openai; `embed_texts` branches on provider. The voyage client uses `output_dimension` rather than `dimensions`.
- All deps are version-pinned in `pyproject.toml` and locked in `uv.lock`.
- No known CVEs flagged (not formally scanned); `bandit` is not wired into CI.
- MIT license; all direct deps are permissively licensed.

---

## Tech Debt / Issues

1. **`approval_gate.py` uses process-global dicts** (`_resolutions`, `_events`, lines 35-36). Multi-worker deployment (e.g. `uvicorn --workers 4`) would silently lose approvals. Single-process deployment is safe; this is the assumed mode.

2. **`_determine_anthropic` parses JSON from free-form rationale text** via regex (`_JSON_RE`, `determination.py:32`). If Sonnet includes a JSON-looking block in its reasoning prose before the terminal JSON, `_parse_decision_json` takes the first match — not the last. This has not caused failures on the calibration set, but is fragile.

3. **`providers.py` cost accumulator is a global mutable float** (`_cost_usd`, line 35). Not thread-safe; concurrent eval runs would produce incorrect totals. Acceptable for serial eval use.

4. **`AuditLog.append()` reads the entire JSONL file to find the last hash** (`_last_hash`, `log.py:56-62`). For long-running production deployments this becomes O(n) per case. A simple cache of the last hash would fix it.

5. **`_local_search` (Jaccard fallback) and the production vector search do not fuse scores** — they are fully separate code paths. If Qdrant is up but returns low-quality results (wrong dimension, stale index), there is no hybrid re-ranking layer.

6. **No input length validation on `case_text`** before the LLM call. Very long case descriptions could exceed model context. The determination prompt already concatenates case text + screening note + eight rule documents.

---

## Extension Points

### Issue #4 — Hybrid (dense + lexical) retrieval

The entire retrieval surface lives in one method:

**`src/compliance_agent/rulebook/indexer.py`, `RulebookIndexer.search()` (line 83)**

```python
def search(self, query: str, top_k: int = 5) -> list[dict[str, object]]:
    try:
        return self._vector_search(query, top_k)
    except Exception:
        ...
        return self._local_search(query, top_k)
```

The hybrid hook goes inside `_vector_search` (or alongside it, with a new `_hybrid_search`
that `search()` calls instead). Specifically:

- **Over-fetch from Qdrant** at `top_k * 3` (or a configurable `fetch_k` parameter), then re-rank by a combined score.
- **Add a lexical pass** (`_local_search` already computes Jaccard; BM25 would be stronger and the `rank-bm25` package is lightweight) over the same candidate pool.
- **Reciprocal Rank Fusion (RRF)** is the simplest no-weight combiner: `score = 1/(k + rank_dense) + 1/(k + rank_sparse)`. No extra config parameter to tune.
- **Return `top_k` from the fused list**, keeping the same return type `list[dict[str, object]]`.

Constraints to preserve:

1. **`search()` signature must not change** — `(self, query: str, top_k: int = 5) -> list[dict[str, object]]`. `rule_retrieval_node` calls it at line 32; the test at `tests/test_retrieval.py:48` asserts `len(result) == rule_retrieval.TOP_K`.
2. **`_local_search` must remain the offline fallback** and continue to produce correct results for `test_local_search_surfaces_relevant_rule` (line 27) and `test_search_falls_back_when_qdrant_unreachable` (line 34). Do not alter its signature or Jaccard logic.
3. **`_ensure_sanctions_rules` in `nodes/sanctions_screening.py` (line 34)** injects AML-046 and AML-007 by rule_id after retrieval whenever a watchlist hit is present. The injected entries use `score=1.0`. Hybrid re-ranking must not re-order or drop the injected entries — they are added after `search()` returns, so they are safe as long as hybrid re-ranking stays inside `search()`.
4. **Score field must be present** in every returned dict (tested at `test_retrieval.py:39`).

The safest implementation shape:

```python
def _hybrid_search(self, query: str, top_k: int) -> list[dict[str, object]]:
    fetch_k = top_k * 3
    dense_results = self._vector_search(query, fetch_k)   # may raise → caller catches
    sparse_results = self._local_search(query, fetch_k)
    # RRF fusion → slice to top_k
    ...

def search(self, query: str, top_k: int = 5) -> list[dict[str, object]]:
    try:
        return self._hybrid_search(query, top_k)
    except Exception as exc:
        log.warning("rulebook.vector_search_failed", error=str(exc), fallback="token_overlap")
        return self._local_search(query, top_k)
```

This keeps the fallback path identical and lets `_hybrid_search` be unit-tested independently.

---

## Other Genuine Gaps Worth Enhancing

**1. `_determine_anthropic` JSON parsing is fragile (determination.py:219-221)**
`_parse_decision_json` takes the *first* regex match of `{"decision": ...}` in the rationale text. If Sonnet emits a hypothetical or quoted JSON block before the terminal decision JSON, the wrong value is picked. Fix: parse from the *last* match, or ask Sonnet to emit the JSON on the final line with a sentinel prefix.

**2. `AuditLog._last_hash()` reads the whole file on every `record()` call (log.py:57-62)**
Each node calls `record()`, so a single case triggers 5-6 full file reads. For production throughput, cache the last hash on `AuditLog.__init__` and update it in `append()`. The current JSONL append is safe but the read is not.

**3. `approval_gate._resolutions` / `_events` are in-process dicts (approval_gate.py:35-36)**
If the service is ever deployed with more than one worker process (or restarted between the Slack post and the officer click), the event is lost and the case stays pending indefinitely. A Redis or Postgres-backed store is the correct fix before any horizontal scaling.

**4. No BM25 or n-gram term index alongside Qdrant during indexing (`indexer.build()`)**
The offline fallback only exists for the case where Qdrant is unreachable. There is no lexical index that runs alongside Qdrant in production. This is directly the issue #4 gap: a PEP case using the phrase "foreign finance minister" (no overlap with "politically exposed person") will score poorly against AML-004 in pure dense retrieval.

**5. Eval judge is called synchronously inside the main event loop (`run_eval.py:105`)**
`asyncio.run(judge_determination(...))` is called inside a `for` loop that is itself not async. Each case's judge call creates and tears down a new event loop. This works correctly but is slow — the 100-case eval makes 100 serial round-trips. Gathering them concurrently (or batching) would cut eval wall time significantly.

**6. No `sanctions_screening` entry in `audit/report.py`'s `_NODE_LABELS` (report.py:17-24)**
The sanctions node calls `record()` and its entry appears in the JSONL log, but the Markdown examiner report renders the node name raw (`"sanctions_screening"`) instead of a human-readable label. Minor, but visible to regulators reading the report.

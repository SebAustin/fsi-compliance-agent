# fsi-compliance-agent

> A compliance-review agent that cites the rule, knows when to abstain, and refuses
> to auto-close a high-risk flag without a human. Built by someone who spent 11 years
> in regulated financial services — and built to survive an examiner reading the audit log.

[![CI](https://github.com/SebAustin/fsi-compliance-agent/actions/workflows/ci.yml/badge.svg)](https://github.com/SebAustin/fsi-compliance-agent/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)

## The error that matters in compliance

Most "AI for compliance" demos report accuracy. Accuracy is the wrong headline.
In compliance the two errors are not symmetric:

- A **false positive** (flagging a clean transaction) costs an analyst ten minutes.
- A **false negative** (missing a transaction that should have been flagged) is the
  regulatory finding, the consent order, the fine.

This agent is built around that asymmetry. The eval reports false-negative rate as
the headline number. The abstention threshold is calibrated at alpha=0.05 — stricter
than a typical RAG system — because the agent should hand uncertainty to a human
rather than auto-clear a case it isn't sure about.

## How it works

1. **Triage** — classify case type and risk tier (fast model).
2. **Rule retrieval** — find the rulebook clauses that apply (Qdrant + embeddings).
3. **Determination** — produce a compliant / flag / needs-review decision, with every
   determination citing the specific rule clause. Uncited → invalid.
4. **Abstain** — if confidence is below the calibrated threshold, route to human review.
5. **Approval gate** — high-risk flags go through a Slack approval gate. A compliance
   officer approves or overrides. The agent never auto-closes a high-risk flag.
6. **Audit** — every step is written to a hash-chained, examiner-grade audit log.

### Provider-agnostic, OpenAI by default

The agent runs on **OpenAI or Anthropic** — set `LLM_PROVIDER` (and `EMBED_PROVIDER`).
The default is OpenAI (`gpt-4.1` family + `text-embedding-3-large`).

The citation contract holds either way, but the mechanism differs:

- **Anthropic** uses the native **Citations API**, which returns verifiable char
  offsets into the source document.
- **OpenAI** has no equivalent, so the agent requests quoted spans via structured
  output and **verifies each quote by locating it inside the cited rule clause** —
  a quote the model didn't actually take from the clause is unverifiable and is
  dropped. A determination left with no verifiable citation is rejected
  (`CitationContractError`). This makes "cite or you can't decide" enforceable on
  either provider.

```mermaid
flowchart LR
    CASE[Case / transaction] --> TR[triage\ntype + risk tier]
    TR --> RR[rule_retrieval\nrulebook clauses]
    RR --> DET[determination\nLLM + verified citations\nconfidence]
    DET --> AB{confidence ≥ τ?}
    AB -->|no| HR[human review queue]
    AB -->|yes| RISK{risk tier?}
    RISK -->|high + flag| AG[Slack approval gate]
    RISK -->|low/med| CLOSE[auto-close with citation]
    AG --> CLOSE
    CLOSE --> AUD[(hash-chained audit log)]
    HR --> AUD
```

## Quickstart

```bash
git clone https://github.com/SebAustin/fsi-compliance-agent && cd fsi-compliance-agent
uv sync && cp .env.example .env   # set OPENAI_API_KEY (or LLM_PROVIDER=anthropic + key)
make index            # build rulebook index
make calibrate        # fit abstention threshold (alpha=0.05) on labeled cases
make review CASE="Wire transfer of $9,500 to a new payee in a high-risk jurisdiction, structured below the $10k reporting threshold"
make eval             # full eval on 80 cases
```

> **No external services?** The agent degrades gracefully for local development:
> with `SLACK_BOT_TOKEN` empty the approval gate runs in dry-run mode, and the test
> suite mocks every network boundary (Anthropic, Voyage, Qdrant, Slack) so
> `make test` runs fully offline.

## Eval results (v0.1.0, 80 labeled cases)

| Metric | Target | v0.1.0 |
|---|---|---|
| **False-negative rate** (missed flags) | ≤ 0.03 | **0.02** |
| Determination accuracy | ≥ 0.85 | **0.87** |
| Citation coverage | 1.00 | **1.00** |
| Abstention rate | report | **19%** |
| Conditional accuracy (auto-decided) | ≥ 0.92 | **0.94** |
| Conformal coverage met (alpha=0.05) | yes | **yes** |
| Cost per case | < $0.03 | **$0.018** |

False-negative rate 0.02: 1 case of 80 was auto-cleared when it should have been
flagged — a layered-structuring pattern the rulebook covers but the retrieval missed.
Tracked as an open issue; the fix is a rule-cross-reference index.

## A note on the data

The rulebook is **synthetic and originally authored** — 40 rules in an AML/BSA-style
structure (reporting thresholds, structuring, sanctions screening, PEP handling,
beneficial-ownership). It is not copied from any real regulation. The 80 cases are
synthetic. This keeps the repo fully shareable while exercising the same logic a
real rulebook would.

## Repository layout

```
src/compliance_agent/
  state.py        CaseState + pydantic models (the contracts)
  graph.py        LangGraph StateGraph wiring
  config.py       pydantic-settings configuration
  nodes/          triage, rule_retrieval, determination, abstain, approval_gate, close
  rulebook/       indexer + rules.jsonl (40 synthetic rules)
  audit/          hash-chained, examiner-grade audit log
  api/server.py   FastAPI: /review /approvals /audit
evals/            run_eval.py (false-negative rate is the headline), judge.py, cases.jsonl
scripts/          build_index.py, calibrate.py, review.py
docs/             architecture, rulebook design, examiner notes
```

## Sources

1. Anthropic. *Citations API documentation.* docs.anthropic.com, 2025.
2. Yadkori et al. *Mitigating LLM Hallucinations via Conformal Abstention.* arXiv 2405.01563, 2024.
3. Anthropic. *Building effective agents.* anthropic.com, 2024.

## License

MIT — see [LICENSE](LICENSE).

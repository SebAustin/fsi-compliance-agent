# LinkedIn / outreach pack

Ready-to-post copy for `fsi-compliance-agent`. Numbers here match the measured v0.1.0
state (100-case calibration + 28-case held-out, OpenAI `gpt-4.1`). Update if you re-run.

Repo: https://github.com/SebAustin/fsi-compliance-agent

---

## Main post (long form)

I spent 11 years building systems in regulated financial services — feeding Federal
Reserve reporting at BNP Paribas, building National Bank of Canada's national mortgage
platform. So when I see "AI for compliance" demos quoting accuracy, I know they're
measuring the wrong thing.

In compliance, the two errors aren't symmetric. A false positive — flagging a clean
transaction — costs an analyst ten minutes. A false negative — missing a transaction that
should have been flagged — is the regulatory finding, the consent order, the fine.

So I spent a week building a compliance-review agent around that asymmetry.

It's a LangGraph agent: triage the case, retrieve the applicable rules, screen names
against a sanctions watchlist, and produce a determination (compliant / flag /
needs-review). Four decisions from the regulated-finance world shaped it:

→ **Every determination cites the specific rule clause.** A determination with no citation
isn't a warning in this system — it raises an error. On OpenAI (no native citations API),
the agent quotes the clause and the code verifies the quote is a verbatim substring of the
actual rule, so it catches fabricated citations. In compliance you cannot clear or flag a
transaction on an uncited basis.

→ **It abstains when it isn't sure.** A conformal threshold (calibrated at alpha=0.05,
stricter than a typical RAG system) routes low-confidence cases to a human instead of
guessing. On a held-out test set the rules were never tuned against, the abstention rate
rose from 5% to 14% — exactly the behaviour you want: more uncertain on unfamiliar cases,
so more goes to a person.

→ **High-risk flags never auto-close.** They route through a Slack approval gate where a
compliance officer approves or overrides (signed, replay-protected callbacks). On timeout
the case stays open — it fails safe toward human review, never toward auto-approval.

→ **The audit log is the product.** Every step is written to a hash-chained, tamper-evident
log. `GET /audit/case/{id}` renders the full trail an examiner actually reads — triage to
cited clause to final decision.

The headline metric is the false-negative rate, and it's **0.00** — on the calibration set
and on the held-out set. The one real limitation (a PEP case where semantic retrieval
missed the rule) is documented in the README and filed as an issue, not hidden — the agent
escalated it to a human rather than guessing, which is the point.

The rulebook (46 AML/BSA-style rules) and the sanctions watchlist are synthetic and
originally authored — no copied regulation, fully shareable. The architecture is the one I
shipped in production, rebuilt on a modern agentic stack.

80 tests, mypy --strict, CI gated on the false-negative rate, ~$0.003 per case.

github.com/SebAustin/fsi-compliance-agent

#AIEngineering #RegTech #FinancialServices #Compliance #LangGraph #LLM

---

## Short variant (hook + link)

Most "AI for compliance" demos report accuracy. In compliance that's the wrong number —
the one that costs money is the *missed* flag.

So I built a compliance agent around that: it cites the exact rule for every decision,
abstains to a human when unsure, never auto-closes a high-risk flag without approval, and
writes a tamper-evident audit log an examiner can read. False-negative rate: 0.00, on a
held-out set too.

11 years in regulated finance, rebuilt on a modern agentic stack (LangGraph, conformal
abstention, Slack HITL, hash-chained audit). Synthetic data, fully shareable.

github.com/SebAustin/fsi-compliance-agent

---

## Interview talking points

- **Why false-negative rate, not accuracy?** Cost asymmetry: a missed flag is the
  consent order; an over-flag is ten analyst-minutes. Reporting accuracy averages over an
  asymmetry that dominates the real cost.
- **How is "cite the rule" enforced, not just prompted?** A compliant/flag decision with
  zero citations raises `CitationContractError`. On OpenAI, each quoted span is verified
  as a verbatim substring of the cited clause — fabricated quotes are dropped, and a
  determination left uncited escalates to a human.
- **Why conformal abstention?** It gives a calibrated, distribution-free way to say "below
  this confidence, hand off." The held-out abstention rate rising (5%→14%) is evidence the
  calibration generalizes — the system gets *appropriately* less certain off-distribution.
- **Why deterministic sanctions screening?** Real programs screen names against a list;
  that's a control, not a judgment call. Exact match forces a human gate; fuzzy near-match
  goes to review (false hit = review time, missed hit = violation).
- **What's the honest weakness?** Pure semantic retrieval has a recall tail (a PEP case
  worded "foreign finance minister" didn't surface the PEP rule). The system fails safe
  (escalates), it's measured on a held-out set, and the fix (hybrid retrieval) is filed as
  issue #4 — I'd rather show the limitation and the safe behaviour than hide it.
- **What would you add for production?** Hybrid retrieval, real watchlist/rulebook
  ingestion, the Slack interactivity deployed behind auth, per-tenant audit storage, and a
  larger independently-labeled evaluation set.

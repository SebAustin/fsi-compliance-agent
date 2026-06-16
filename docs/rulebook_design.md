# Rulebook design

The rulebook is **synthetic and originally authored**. It is not copied from any real
regulation. It mirrors the *structure* of an AML/BSA-style program so the agent exercises
the same retrieval-and-citation logic a real rulebook would, while keeping the repo fully
shareable.

## Schema

Each rule is one JSON line in [`src/compliance_agent/rulebook/rules.jsonl`](../src/compliance_agent/rulebook/rules.jsonl):

```json
{"rule_id": "AML-002", "title": "Structuring Prohibition", "category": "structuring",
 "clause": "Conducting transactions in amounts deliberately kept below the $10,000 ..."}
```

- `rule_id` — stable identifier; this is what a determination cites.
- `title` — short human label.
- `category` — one of the coverage pillars below.
- `clause` — the authoritative text. This exact string is what gets embedded for
  retrieval and what gets passed to the Citations API as a document, so cited char
  offsets are verifiable against it.

## Coverage (45 rules)

The rulebook spans the pillars an examiner expects:

| Category | Theme | Example rules |
|---|---|---|
| `reporting` | threshold reporting & aggregation | AML-001, AML-019, AML-028, AML-033 |
| `structuring` | sub-threshold & layered evasion | AML-002, AML-006, AML-018, AML-027, AML-034 |
| `sanctions` | watchlist & ownership screening | AML-003, AML-007, AML-022, AML-036 |
| `pep` | politically exposed persons & associates | AML-004, AML-021 |
| `kyc` | identity & beneficial ownership | AML-005, AML-020, AML-023, AML-024, AML-029, AML-040 |
| `edd` | enhanced due diligence | AML-014, AML-015, AML-016, AML-032 |
| `monitoring` | behavioral typologies | AML-008..013, AML-025, AML-026, AML-031, AML-035, AML-038, AML-039 |
| `wire` / `recordkeeping` | transfer integrity | AML-010, AML-030, AML-037 |
| `clearance` | safe-harbor / clearance basis | AML-041..045 |

### Why a `clearance` tier exists

AML rulebooks are written as **prohibitions and triggers** ("flag if X"), not affirmative
permissions — so a genuinely clean transaction often has no rule that says "this is
allowed." But the citation contract requires *every* determination, including a clearance,
to cite the rule it relied on (you should be able to show an examiner *why* you cleared a
case, not just that you did). The `clearance` rules (AML-041..045) provide that affirmative
basis: routine low-value activity, verified counterparties, below-threshold cash, salary /
benefit payments, and own-account transfers. A `compliant` determination cites the
clearance rule (or the threshold rule the amount falls under) and explains why it is not
triggered.

## How a clause becomes a citation

1. Retrieval embeds the case text and finds the top-k clauses (`RulebookIndexer.search`).
2. Those clauses are passed to the determination model. On Anthropic they go as
   **citations-enabled documents**; on OpenAI they go as labelled context and the model
   returns quoted spans.
3. The model cites spans inside a clause; we map each span back to its `rule_id` and store
   `(rule_id, cited_text, start_char, end_char)` on the `Determination`. On OpenAI the
   offsets are computed by verifying the quote is a verbatim substring of the clause.
4. The close node writes the cited `rule_id`s into the audit log.

## Known gap: cross-references

Some real-world patterns implicate two rules at once — e.g. a layered-structuring case
touches both the single-transaction reporting rule (AML-001) and the structuring rule
(AML-002/AML-006). Pure semantic retrieval can surface the reporting rule and miss its
associated structuring rule. This is the root cause of the one tracked false negative; the
fix is a rule cross-reference index (see the open issues).

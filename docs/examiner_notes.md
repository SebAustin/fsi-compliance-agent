# Examiner notes

What would a regulator actually look for when reading this system's output? The audit log
is the product surface, so this document states the questions an examiner asks and where
the answer lives.

## 1. Can every decision be traced to a rule?

Yes. Every `compliant`/`flag` determination carries at least one citation
`(rule_id, cited_text, start_char, end_char)`. An uncited determination cannot be
produced — the determination node raises `CitationContractError` before the case can
close. Citation coverage is reported by the eval and gated in CI at 1.00.

## 2. Is the audit trail tamper-evident?

Yes. The audit log (`audit/log.py`) is append-only and hash-chained: each entry's
`hash_self = sha256(hash_prev + canonical(entry))`. `GET /audit/verify` recomputes the
whole chain. Editing a field, reordering a line, or deleting an entry all break the chain
and return `{"valid": false}`. See `tests/test_audit.py` for the tamper and deletion cases.

## 3. What happens when the system is unsure?

It abstains. Confidence below the calibrated conformal threshold (alpha=0.05) routes the
case to human review instead of an auto-decision. The threshold is *calibrated*, not
hardcoded — `scripts/calibrate.py` fits it on the labeled set and writes it to
`.calibration.json`. The abstention rate is reported every eval run.

## 4. Who approves a high-risk flag?

A human. A `high` risk-tier `flag` never auto-closes; it routes through the Slack approval
gate where a compliance officer **approves** (upholds the flag) or **overrides** (clears
the case). Button clicks come back as a signed Slack interaction to
`POST /slack/interactivity`, whose request signature is verified (with replay protection)
before it resolves the gate; `POST /approvals/{id}` is an equivalent programmatic path. On
timeout the case stays `pending` — the system never auto-approves. The audit trail records
that approval was required and how it resolved.

## 5. What is the system's error profile?

Reported directly, with the cost-asymmetric error as the headline:

- **False-negative rate** — flags that were auto-cleared. This is the regulatory-risk
  number and is gated in CI at ≤ 0.03.
- **Conditional accuracy** — accuracy among auto-decided (non-abstained) cases.
- **Citation coverage**, **abstention rate**, **cost per case**.

## Reading a single case (per the roadmap)

A per-case examiner export (`GET /audit/case/{id}`) that renders the full ordered trail —
triage → rules retrieved → determination → cited clause text → abstention/approval → final
decision — is the next planned feature. `AuditLog.read_case()` already returns the ordered
trail; the Markdown rendering is the open work item.

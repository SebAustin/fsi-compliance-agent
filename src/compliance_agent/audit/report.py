"""Render a single case's audit trail as a Markdown report for examiners.

The audit log stores rule_ids (the durable reference); this resolves each cited
rule_id to its title and clause text from the rulebook so a regulator can read the
exact basis for every step without cross-referencing another document.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from compliance_agent.audit.log import AuditEntry

_NODE_LABELS = {
    "triage": "Triage",
    "rule_retrieval": "Rule retrieval",
    "sanctions_screening": "Sanctions screening",
    "determination": "Determination",
    "abstain": "Abstention check",
    "approval_gate": "Approval gate",
    "close": "Close",
}


def _fmt_confidence(value: float | None) -> str:
    return "—" if value is None else f"{value:.2f}"


def render_case_report(
    case_id: str,
    entries: Sequence[AuditEntry],
    rules_by_id: Mapping[str, Mapping[str, str]],
    *,
    integrity_ok: bool,
) -> str:
    """Render the ordered audit trail for one case as Markdown."""
    integrity = "VERIFIED ✓" if integrity_ok else "FAILED ✗ — chain tampered"
    lines: list[str] = [
        f"# Compliance audit trail — case `{case_id}`",
        "",
        f"- **Audit-log integrity:** {integrity}",
        f"- **Recorded steps:** {len(entries)}",
        "",
        "## Timeline",
        "",
        "| # | Timestamp (UTC) | Step | Outcome | Confidence | Rules cited |",
        "| - | --------------- | ---- | ------- | ---------- | ----------- |",
    ]

    cited_ids: list[str] = []
    for i, entry in enumerate(entries, start=1):
        label = _NODE_LABELS.get(entry["node"], entry["node"])
        rule_ids = entry["rule_ids_cited"]
        for rid in rule_ids:
            if rid not in cited_ids:
                cited_ids.append(rid)
        lines.append(
            f"| {i} | {entry['timestamp']} | {label} | {entry['decision']} | "
            f"{_fmt_confidence(entry['confidence'])} | {', '.join(rule_ids) or '—'} |"
        )

    lines += ["", "## Cited rules", ""]
    if not cited_ids:
        lines.append("_No rules were cited in this trail._")
    for rid in cited_ids:
        rule = rules_by_id.get(rid)
        if rule is None:
            lines += [f"### {rid}", "", "_Rule not found in current rulebook._", ""]
            continue
        lines += [f"### {rid} — {rule.get('title', '')}", "", f"> {rule.get('clause', '')}", ""]

    return "\n".join(lines).rstrip() + "\n"

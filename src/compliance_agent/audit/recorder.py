"""Convenience for appending a node transition to the configured audit log.

Every node records its transition so the per-case trail (triage -> retrieval ->
determination -> abstain -> approval -> close) is reconstructable for examiner export.
"""

from __future__ import annotations

from compliance_agent.audit.log import AuditLog
from compliance_agent.config import get_settings


def record(
    case_id: str,
    node: str,
    decision: str,
    rule_ids: list[str] | None = None,
    confidence: float | None = None,
) -> None:
    """Append one node transition to the hash-chained audit log."""
    AuditLog(get_settings().audit_log_path).append(
        case_id=case_id,
        node=node,
        decision=decision,
        rule_ids=rule_ids,
        confidence=confidence,
    )

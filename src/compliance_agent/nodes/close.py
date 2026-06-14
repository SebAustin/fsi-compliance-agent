"""Close node — set the final decision (honoring overrides) and write the audit trail.

An officer "override" on a high-risk flag clears the case to compliant; an "approve"
upholds the agent's flag. Every closed case appends a row to the hash-chained audit
log with the cited rule ids and the confidence.
"""

from __future__ import annotations

import structlog

from compliance_agent.audit.log import AuditLog
from compliance_agent.config import get_settings
from compliance_agent.state import CaseState, Decision

log = structlog.get_logger(__name__)


def _final_decision(state: CaseState) -> Decision:
    determination = state["determination"]
    if state.get("approval_status") == "overridden":
        # The compliance officer overrode the agent's flag — case is cleared.
        return "compliant"
    return determination.decision


async def close_node(state: CaseState) -> CaseState:
    """Finalize the case and append the audit entry."""
    settings = get_settings()
    determination = state["determination"]
    final = _final_decision(state)

    audit = AuditLog(settings.audit_log_path)
    audit.append(
        case_id=state["case_id"],
        node="close",
        decision=final,
        rule_ids=[c.rule_id for c in determination.citations],
        confidence=determination.confidence,
    )

    log.info("close.complete", case_id=state["case_id"], final_decision=final)
    return {**state, "final_decision": final}

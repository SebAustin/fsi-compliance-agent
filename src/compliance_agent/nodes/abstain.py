"""Abstention node — route low-confidence determinations to human review.

Uses split-conformal nonconformity: nonconformity = 1 - confidence. If it exceeds
the calibrated threshold τ (fit at alpha=0.05 on the labeled set), the agent
abstains rather than guessing. Also sets ``approval_required`` for high-risk flags,
which the router uses to send the case through the Slack approval gate.
"""

from __future__ import annotations

import structlog

from compliance_agent.config import get_settings
from compliance_agent.state import CaseState

log = structlog.get_logger(__name__)


def nonconformity(confidence: float) -> float:
    """Conformal nonconformity score for a determination."""
    return 1.0 - confidence


async def abstain_node(state: CaseState) -> CaseState:
    """Decide whether to abstain and whether an approval gate is required."""
    settings = get_settings()
    threshold = settings.calibrated_threshold()
    determination = state["determination"]

    score = nonconformity(determination.confidence)
    abstained = score > threshold

    approval_required = (
        not abstained and state.get("risk_tier") == "high" and determination.decision == "flag"
    )

    log.info(
        "abstain.evaluated",
        case_id=state["case_id"],
        nonconformity=round(score, 4),
        threshold=round(threshold, 4),
        abstained=abstained,
        approval_required=approval_required,
    )
    return {**state, "abstained": abstained, "approval_required": approval_required}

"""Approval-gate node — Slack human-in-the-loop for high-risk flags.

A determination with risk_tier == "high" AND decision == "flag" never auto-closes.
It posts a Slack interactive message (Approve / Override / Request-Info) and blocks
until a compliance officer responds or the configured timeout elapses. On timeout
the status stays "pending" and the case stays open — the gate fails safe toward
human review, never toward auto-approval.

Resolutions arrive out-of-band via ``resolve_approval`` (wired to the FastAPI
``POST /approvals/{id}`` endpoint and to Slack interaction callbacks).
"""

from __future__ import annotations

import asyncio

import structlog

from compliance_agent.config import Settings, get_settings
from compliance_agent.state import CaseState

log = structlog.get_logger(__name__)

_POLL_INTERVAL_S = 1.0
_VALID_ACTIONS: frozenset[str] = frozenset({"approve", "override", "request_info"})
_ACTION_TO_STATUS: dict[str, str] = {
    "approve": "approved",
    "override": "overridden",
    "request_info": "pending",
}

# Process-wide registry of pending approvals: case_id -> resolved status.
_resolutions: dict[str, str] = {}
_events: dict[str, asyncio.Event] = {}


def register_pending(case_id: str) -> asyncio.Event:
    """Register a case as awaiting approval and return its wait event."""
    event = asyncio.Event()
    _events[case_id] = event
    _resolutions.pop(case_id, None)
    return event


def resolve_approval(case_id: str, action: str) -> str:
    """Resolve a pending approval. Returns the resulting status."""
    if action not in _VALID_ACTIONS:
        raise ValueError(f"Unknown approval action: {action!r}")
    status = _ACTION_TO_STATUS[action]
    _resolutions[case_id] = status
    event = _events.get(case_id)
    if event is not None:
        event.set()
    log.info("approval.resolved", case_id=case_id, action=action, status=status)
    return status


def pending_case_ids() -> list[str]:
    """Case ids currently awaiting an approval decision."""
    return [cid for cid in _events if cid not in _resolutions]


def _post_to_slack(case_id: str, determination_summary: str, settings: Settings) -> None:
    """Post the interactive approval message. No-op in dry-run (no bot token)."""
    if not settings.slack_bot_token:
        log.warning("approval.slack_dry_run", case_id=case_id)
        return
    from slack_sdk import WebClient

    client = WebClient(token=settings.slack_bot_token)
    client.chat_postMessage(
        channel=settings.slack_approval_channel,
        text=f"High-risk flag requires approval: {case_id}",
        blocks=[
            {"type": "section", "text": {"type": "mrkdwn", "text": determination_summary}},
            {
                "type": "actions",
                "block_id": f"approval::{case_id}",
                "elements": [
                    {
                        "type": "button",
                        "action_id": "approve",
                        "text": {"type": "plain_text", "text": "Approve"},
                        "style": "primary",
                    },
                    {
                        "type": "button",
                        "action_id": "override",
                        "text": {"type": "plain_text", "text": "Override"},
                        "style": "danger",
                    },
                    {
                        "type": "button",
                        "action_id": "request_info",
                        "text": {"type": "plain_text", "text": "Request Info"},
                    },
                ],
            },
        ],
    )


async def _await_resolution(case_id: str, event: asyncio.Event, timeout_s: int) -> str:
    """Wait for a resolution or time out. Timeout keeps the case 'pending'."""
    try:
        await asyncio.wait_for(event.wait(), timeout=timeout_s)
    except TimeoutError:
        log.warning("approval.timeout", case_id=case_id, status="pending")
        return "pending"
    return _resolutions.get(case_id, "pending")


async def approval_gate_node(state: CaseState) -> CaseState:
    """Block a high-risk flag on human approval; default to pending on timeout."""
    if not state.get("approval_required"):
        return {**state, "approval_status": "not_required"}

    settings = get_settings()
    case_id = state["case_id"]
    determination = state["determination"]
    summary = (
        f"*Case* `{case_id}`\n*Decision*: {determination.decision} "
        f"(confidence {determination.confidence:.2f})\n"
        f"*Cited rules*: {', '.join(c.rule_id for c in determination.citations)}\n"
        f"{determination.rationale[:600]}"
    )

    event = register_pending(case_id)
    _post_to_slack(case_id, summary, settings)
    status = await _await_resolution(case_id, event, settings.approval_timeout_s)

    log.info("approval.gate_complete", case_id=case_id, status=status)
    return {**state, "approval_status": status}

"""Approval gate: posts to Slack; timeout must NOT auto-approve."""

from __future__ import annotations

import asyncio

import pytest

from compliance_agent.config import Settings
from compliance_agent.nodes import approval_gate as gate
from compliance_agent.state import CaseState
from tests.conftest import make_determination


def _state(*, approval_required: bool = True) -> CaseState:
    return {
        "case_id": "c-approve",
        "case_text": "x",
        "risk_tier": "high",
        "determination": make_determination(decision="flag", confidence=0.95),
        "approval_required": approval_required,
    }


async def test_posts_message_for_high_risk_flag(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    posted: list[str] = []
    monkeypatch.setattr(gate, "_post_to_slack", lambda case_id, *_: posted.append(case_id))
    settings.approval_timeout_s = 0  # return immediately as pending

    result = await gate.approval_gate_node(_state())
    assert posted == ["c-approve"]
    assert result["approval_status"] == "pending"


async def test_timeout_does_not_auto_approve(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(gate, "_post_to_slack", lambda *_: None)
    settings.approval_timeout_s = 0
    result = await gate.approval_gate_node(_state())
    assert result["approval_status"] == "pending"  # fail safe toward human review


async def test_resolution_approves(settings: Settings, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(gate, "_post_to_slack", lambda *_: None)
    settings.approval_timeout_s = 5

    task = asyncio.create_task(gate.approval_gate_node(_state()))
    await asyncio.sleep(0.05)
    gate.resolve_approval("c-approve", "approve")
    result = await task
    assert result["approval_status"] == "approved"


async def test_override_status(settings: Settings, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(gate, "_post_to_slack", lambda *_: None)
    settings.approval_timeout_s = 5

    task = asyncio.create_task(gate.approval_gate_node(_state()))
    await asyncio.sleep(0.05)
    gate.resolve_approval("c-approve", "override")
    result = await task
    assert result["approval_status"] == "overridden"


async def test_not_required_skips_gate(settings: Settings) -> None:
    result = await gate.approval_gate_node(_state(approval_required=False))
    assert result["approval_status"] == "not_required"


def test_resolve_invalid_action_raises() -> None:
    with pytest.raises(ValueError, match="Unknown approval action"):
        gate.resolve_approval("c-x", "delete")


async def test_dry_run_post_no_token(settings: Settings) -> None:
    settings.slack_bot_token = ""
    # Should not raise even without slack-sdk configured.
    gate._post_to_slack("c-1", "summary", settings)

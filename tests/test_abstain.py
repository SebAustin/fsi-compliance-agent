"""Abstention node: low confidence abstains; high-risk flags require approval."""

from __future__ import annotations

import pytest

from compliance_agent.config import Settings
from compliance_agent.nodes.abstain import abstain_node, nonconformity
from compliance_agent.state import CaseState
from tests.conftest import make_determination


def _state(determination_kwargs: dict[str, object], risk_tier: str = "high") -> CaseState:
    return {
        "case_id": "c-1",
        "case_text": "x",
        "risk_tier": risk_tier,  # type: ignore[typeddict-item]
        "determination": make_determination(**determination_kwargs),  # type: ignore[arg-type]
    }


def test_nonconformity() -> None:
    assert nonconformity(0.9) == pytest.approx(0.1)


async def test_low_confidence_abstains(settings: Settings) -> None:
    settings.abstention_threshold = 0.30
    result = await abstain_node(_state({"decision": "flag", "confidence": 0.5}))
    assert result["abstained"] is True
    assert result["approval_required"] is False  # abstained cases skip the gate


async def test_high_confidence_high_risk_flag_requires_approval(settings: Settings) -> None:
    settings.abstention_threshold = 0.30
    result = await abstain_node(_state({"decision": "flag", "confidence": 0.95}))
    assert result["abstained"] is False
    assert result["approval_required"] is True


async def test_low_risk_flag_does_not_require_approval(settings: Settings) -> None:
    settings.abstention_threshold = 0.30
    result = await abstain_node(_state({"decision": "flag", "confidence": 0.95}, risk_tier="low"))
    assert result["approval_required"] is False


async def test_compliant_does_not_require_approval(settings: Settings) -> None:
    settings.abstention_threshold = 0.30
    result = await abstain_node(_state({"decision": "compliant", "confidence": 0.95}))
    assert result["approval_required"] is False

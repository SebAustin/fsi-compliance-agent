"""Triage node: structuring case classifies as high risk."""

from __future__ import annotations

import pytest

from compliance_agent.config import Settings
from compliance_agent.nodes import triage
from compliance_agent.state import CaseState


def _state() -> CaseState:
    return {
        "case_id": "c-1",
        "case_text": "Customer made repeated cash deposits just below $10,000 across branches.",
    }


async def test_structuring_is_high_risk(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        triage,
        "_triage_llm",
        lambda *_: {"case_type": "structuring", "risk_tier": "high"},
    )
    result = await triage.triage_node(_state())
    assert result["risk_tier"] == "high"
    assert result["case_type"] == "structuring"


async def test_invalid_tier_defaults_to_high(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        triage,
        "_triage_llm",
        lambda *_: {"case_type": "weird", "risk_tier": "catastrophic"},
    )
    result = await triage.triage_node(_state())
    assert result["risk_tier"] == "high"  # fail safe: unknown escalates


async def test_low_risk_passthrough(settings: Settings, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        triage,
        "_triage_llm",
        lambda *_: {"case_type": "payroll", "risk_tier": "low"},
    )
    result = await triage.triage_node(_state())
    assert result["risk_tier"] == "low"


def test_coerce_tier_normalizes_case() -> None:
    assert triage._coerce_tier("HIGH") == "high"
    assert triage._coerce_tier(" Medium ") == "medium"

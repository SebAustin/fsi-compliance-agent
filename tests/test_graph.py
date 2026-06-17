"""End-to-end graph routing with every network boundary mocked."""

from __future__ import annotations

import pytest

from compliance_agent.audit.log import AuditLog
from compliance_agent.config import Settings
from compliance_agent.graph import build_graph
from compliance_agent.nodes import approval_gate, determination, triage


def _mock_triage(monkeypatch: pytest.MonkeyPatch, tier: str) -> None:
    monkeypatch.setattr(triage, "_triage_llm", lambda *_: {"case_type": "t", "risk_tier": tier})


def _mock_determination(
    monkeypatch: pytest.MonkeyPatch, decision: str, confidence: float, *, cited: bool = True
) -> None:
    citations = (
        [{"rule_id": "AML-002", "cited_text": "x", "start_char": 0, "end_char": 1}] if cited else []
    )
    monkeypatch.setattr(
        determination,
        "_determine_llm",
        lambda *_: {
            "decision": decision,
            "rationale": "r",
            "confidence": confidence,
            "citations": citations,
        },
    )


async def test_high_risk_flag_routes_through_approval(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings.abstention_threshold = 0.5
    _mock_triage(monkeypatch, "high")
    _mock_determination(monkeypatch, "flag", 0.95)
    monkeypatch.setattr(approval_gate, "_post_to_slack", lambda *_: None)

    async def _approve(*_: object) -> str:
        return "approved"

    monkeypatch.setattr(approval_gate, "_await_resolution", _approve)

    graph = build_graph()
    state = await graph.ainvoke({"case_id": "c-1", "case_text": "structuring below threshold"})
    assert state["approval_status"] == "approved"
    assert state["final_decision"] == "flag"
    assert AuditLog(settings.audit_log_path).verify() is True


async def test_override_clears_case(settings: Settings, monkeypatch: pytest.MonkeyPatch) -> None:
    settings.abstention_threshold = 0.5
    _mock_triage(monkeypatch, "high")
    _mock_determination(monkeypatch, "flag", 0.95)
    monkeypatch.setattr(approval_gate, "_post_to_slack", lambda *_: None)

    async def _override(*_: object) -> str:
        return "overridden"

    monkeypatch.setattr(approval_gate, "_await_resolution", _override)

    graph = build_graph()
    state = await graph.ainvoke({"case_id": "c-2", "case_text": "structuring below threshold"})
    assert state["final_decision"] == "compliant"


async def test_low_risk_compliant_auto_closes(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings.abstention_threshold = 0.5
    _mock_triage(monkeypatch, "low")
    _mock_determination(monkeypatch, "compliant", 0.97)

    graph = build_graph()
    state = await graph.ainvoke({"case_id": "c-3", "case_text": "routine payroll deposit"})
    assert state["final_decision"] == "compliant"
    assert state.get("approval_required") is False


async def test_low_confidence_abstains_to_human(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings.abstention_threshold = 0.2
    _mock_triage(monkeypatch, "high")
    _mock_determination(monkeypatch, "flag", 0.5)

    graph = build_graph()
    state = await graph.ainvoke({"case_id": "c-4", "case_text": "ambiguous case"})
    assert state["abstained"] is True
    assert "final_decision" not in state  # routed to human review, not closed


async def test_uncited_determination_escalates_to_human(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An ungrounded flag (retrieval missed the rule) escalates, never crashes."""
    settings.abstention_threshold = 0.5
    _mock_triage(monkeypatch, "high")
    _mock_determination(monkeypatch, "flag", 0.99, cited=False)  # uncited -> contract error

    graph = build_graph()
    state = await graph.ainvoke({"case_id": "c-5", "case_text": "ungroundable flag"})
    assert state["abstained"] is True
    assert state["escalation_reason"] == "uncited"
    assert "final_decision" not in state  # human review, not auto-closed

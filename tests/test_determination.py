"""Determination node: the citation contract is the critical case."""

from __future__ import annotations

import pytest

from compliance_agent.config import Settings
from compliance_agent.nodes import determination as det
from compliance_agent.nodes.exceptions import CitationContractError
from compliance_agent.state import CaseState


def _state() -> CaseState:
    return {
        "case_id": "c-1",
        "case_text": "Customer split a deposit below the $10,000 threshold.",
        "risk_tier": "high",
        "retrieved_rules": [
            {
                "rule_id": "AML-002",
                "title": "Structuring",
                "category": "structuring",
                "clause": "Deliberately keeping transactions below the threshold is prohibited.",
                "score": 0.9,
            },
        ],
    }


async def test_valid_flag_with_citations(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        det,
        "_determine_llm",
        lambda *_: {
            "decision": "flag",
            "rationale": "Below-threshold structuring pattern.",
            "confidence": 0.88,
            "citations": [
                {
                    "rule_id": "AML-002",
                    "cited_text": "below the threshold",
                    "start_char": 0,
                    "end_char": 19,
                },
                {
                    "rule_id": "AML-002",
                    "cited_text": "prohibited",
                    "start_char": 20,
                    "end_char": 30,
                },
            ],
        },
    )
    result = await det.determination_node(_state())
    determination = result["determination"]
    assert determination.decision == "flag"
    assert len(determination.citations) == 2


async def test_uncited_flag_raises(settings: Settings, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        det,
        "_determine_llm",
        lambda *_: {
            "decision": "flag",
            "rationale": "Looks suspicious.",
            "confidence": 0.7,
            "citations": [],
        },
    )
    with pytest.raises(CitationContractError):
        await det.determination_node(_state())


async def test_uncited_compliant_raises(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        det,
        "_determine_llm",
        lambda *_: {
            "decision": "compliant",
            "rationale": "Fine.",
            "confidence": 0.95,
            "citations": [],
        },
    )
    with pytest.raises(CitationContractError):
        await det.determination_node(_state())


async def test_needs_review_allows_no_citation(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        det,
        "_determine_llm",
        lambda *_: {
            "decision": "needs_review",
            "rationale": "Unclear.",
            "confidence": 0.4,
            "citations": [],
        },
    )
    result = await det.determination_node(_state())
    assert result["determination"].decision == "needs_review"


def test_parse_decision_json_handles_missing() -> None:
    decision, confidence = det._parse_decision_json("no json here")
    assert decision == "needs_review"
    assert confidence == 0.0


def test_build_documents_enables_citations() -> None:
    docs = det._build_documents([{"rule_id": "AML-001", "clause": "text"}])
    assert docs[0]["citations"] == {"enabled": True}
    assert docs[0]["title"] == "AML-001"

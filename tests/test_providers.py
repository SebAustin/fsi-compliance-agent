"""Provider routing and the OpenAI citation-verification path."""

from __future__ import annotations

import pytest

from compliance_agent import providers
from compliance_agent.config import Settings
from compliance_agent.nodes import determination as det
from compliance_agent.nodes import triage
from compliance_agent.nodes.exceptions import CitationContractError
from compliance_agent.state import CaseState

_RULES: list[dict[str, object]] = [
    {
        "rule_id": "AML-002",
        "title": "Structuring",
        "category": "structuring",
        "clause": "Conducting transactions deliberately kept below the $10,000 threshold is prohibited.",
        "score": 0.9,
    },
]


def _state() -> CaseState:
    return {
        "case_id": "c-1",
        "case_text": "Customer split a deposit below the $10,000 threshold.",
        "risk_tier": "high",
        "retrieved_rules": _RULES,
    }


def test_verify_citations_keeps_verbatim_quote() -> None:
    raw = [{"rule_id": "AML-002", "cited_text": "below the $10,000 threshold"}]
    verified = det._verify_citations(raw, _RULES)
    assert len(verified) == 1
    clause = str(_RULES[0]["clause"])
    start, end = verified[0]["start_char"], verified[0]["end_char"]
    assert clause[start:end] == "below the $10,000 threshold"  # offsets are exact


def test_verify_citations_drops_hallucinated_quote() -> None:
    raw = [{"rule_id": "AML-002", "cited_text": "this text is not in the clause"}]
    assert det._verify_citations(raw, _RULES) == []


def test_verify_citations_drops_unknown_rule_id() -> None:
    raw = [{"rule_id": "AML-999", "cited_text": "below the $10,000 threshold"}]
    assert det._verify_citations(raw, _RULES) == []


@pytest.mark.asyncio
async def test_openai_determination_verifies_and_passes(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings.llm_provider = "openai"
    monkeypatch.setattr(
        providers,
        "openai_chat",
        lambda *_a, **_k: (
            '{"decision": "flag", "confidence": 0.9, "rationale": "structuring", '
            '"citations": [{"rule_id": "AML-002", "cited_text": "below the $10,000 threshold"}]}'
        ),
    )
    result = await det.determination_node(_state())
    determination = result["determination"]
    assert determination.decision == "flag"
    assert determination.citations[0].rule_id == "AML-002"


@pytest.mark.asyncio
async def test_openai_flag_with_only_hallucinated_quote_raises(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings.llm_provider = "openai"
    monkeypatch.setattr(
        providers,
        "openai_chat",
        lambda *_a, **_k: (
            '{"decision": "flag", "confidence": 0.9, "rationale": "x", '
            '"citations": [{"rule_id": "AML-002", "cited_text": "fabricated quote"}]}'
        ),
    )
    # The only citation is unverifiable -> dropped -> uncited flag -> contract error.
    with pytest.raises(CitationContractError):
        await det.determination_node(_state())


def test_triage_dispatches_to_openai(settings: Settings, monkeypatch: pytest.MonkeyPatch) -> None:
    settings.llm_provider = "openai"
    captured: dict[str, str] = {}

    def _fake_openai_chat(_s: Settings, model: str, *_a: object, **_k: object) -> str:
        captured["model"] = model
        return '{"case_type": "structuring", "risk_tier": "high"}'

    monkeypatch.setattr(providers, "openai_chat", _fake_openai_chat)
    result = triage._triage_llm("structuring case", settings)
    assert result["risk_tier"] == "high"
    assert captured["model"] == settings.openai_triage_model


def test_cost_accumulator_records_and_resets() -> None:
    providers.reset_cost()
    assert providers.total_cost_usd() == 0.0
    # gpt-4.1 is $2/1M input, $8/1M output -> 1M in + 1M out = $10.
    providers._record_cost("gpt-4.1", 1_000_000, 1_000_000)
    assert providers.total_cost_usd() == pytest.approx(10.0)
    providers._record_cost("unknown-model", 5_000_000, 5_000_000)  # untracked -> $0
    assert providers.total_cost_usd() == pytest.approx(10.0)
    providers.reset_cost()
    assert providers.total_cost_usd() == 0.0


def test_triage_dispatches_to_anthropic(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings.llm_provider = "anthropic"
    monkeypatch.setattr(
        providers,
        "anthropic_chat",
        lambda *_a, **_k: '{"case_type": "payroll", "risk_tier": "low"}',
    )
    result = triage._triage_llm("payroll", settings)
    assert result["risk_tier"] == "low"

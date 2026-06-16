"""Rulebook loading, offline retrieval, and the retrieval node."""

from __future__ import annotations

import pytest

from compliance_agent.config import Settings
from compliance_agent.nodes import rule_retrieval
from compliance_agent.rulebook.indexer import RulebookIndexer, load_rules
from compliance_agent.state import CaseState


def test_load_rules_has_full_rulebook() -> None:
    rules = load_rules()
    assert len(rules) == 45
    assert all({"rule_id", "title", "category", "clause"} <= set(r) for r in rules)


def test_rulebook_has_clearance_basis_rules() -> None:
    """A 'compliant' determination needs an affirmative clause to cite."""
    rules = load_rules()
    clearance = [r for r in rules if r["category"] == "clearance"]
    assert len(clearance) == 5
    assert {r["rule_id"] for r in clearance} == {f"AML-0{n}" for n in range(41, 46)}


def test_local_search_surfaces_relevant_rule(settings: Settings) -> None:
    indexer = RulebookIndexer(settings)
    results = indexer._local_search("politically exposed person senior official transfer", top_k=5)
    assert any(r["rule_id"] == "AML-004" for r in results)
    assert results[0]["score"] >= results[-1]["score"]


def test_search_falls_back_when_qdrant_unreachable(settings: Settings) -> None:
    settings.qdrant_url = "http://127.0.0.1:9"  # nothing listening -> fallback
    indexer = RulebookIndexer(settings)
    results = indexer.search("beneficial ownership unverified legal entity", top_k=3)
    assert len(results) == 3
    assert "score" in results[0]


async def test_retrieval_node_writes_rules(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(rule_retrieval, "_indexer", RulebookIndexer(settings))
    state: CaseState = {"case_id": "c-1", "case_text": "sanctions watchlist exact name match"}
    result = await rule_retrieval.rule_retrieval_node(state)
    assert len(result["retrieved_rules"]) == rule_retrieval.TOP_K

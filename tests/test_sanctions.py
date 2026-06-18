"""Sanctions watchlist screening: exact/fuzzy matching and the screening node."""

from __future__ import annotations

import pytest

from compliance_agent.config import Settings
from compliance_agent.nodes import sanctions_screening as scr
from compliance_agent.sanctions import load_watchlist, normalize, screen_text
from compliance_agent.state import CaseState

_WL = load_watchlist()


def test_normalize_strips_punctuation_and_case() -> None:
    assert normalize("Helena Brandt-Vogel!") == "helena brandt vogel"


def test_exact_match_by_primary_name() -> None:
    hits = screen_text("Wire to a payee named Dmitri Sokolov today.", _WL)
    assert len(hits) == 1
    assert hits[0].watchlist_id == "SDN-006"
    assert hits[0].match_type == "exact"
    assert hits[0].score == 1.0


def test_exact_match_by_alias() -> None:
    hits = screen_text("Payment to Oceanic Bridge Petroleum for fuel.", _WL)
    assert hits[0].watchlist_id == "SDN-010"
    assert hits[0].match_type == "exact"


def test_fuzzy_near_match_flagged_below_one() -> None:
    hits = screen_text("Transfer to a beneficiary spelled Viktor Morozof.", _WL)
    assert len(hits) == 1
    assert hits[0].watchlist_id == "SDN-001"
    assert hits[0].match_type == "fuzzy"
    assert 0.85 <= hits[0].score < 1.0


def test_clean_name_no_match() -> None:
    assert screen_text("Invoice paid to David Thompson, a verified vendor.", _WL) == []


def test_fuzzy_threshold_respected() -> None:
    # A high threshold suppresses a near-match that a lower one would catch.
    text = "Transfer to a payee named Rashid Al-Mansour."
    assert screen_text(text, _WL, fuzzy_threshold=0.99) == []
    assert screen_text(text, _WL, fuzzy_threshold=0.85)


@pytest.mark.asyncio
async def test_screening_node_injects_sanctions_rules_on_hit(settings: Settings) -> None:
    state: CaseState = {
        "case_id": "c-1",
        "case_text": "Wire to Crimson Delta Trading FZE.",
        "retrieved_rules": [
            {
                "rule_id": "AML-001",
                "title": "x",
                "category": "reporting",
                "clause": "y",
                "score": 0.3,
            }
        ],
    }
    result = await scr.sanctions_screening_node(state)
    assert result["sanctions_hits"][0]["watchlist_id"] == "SDN-005"
    rule_ids = {r["rule_id"] for r in result["retrieved_rules"]}
    assert {"AML-046", "AML-007"} <= rule_ids  # made citable for the determination
    assert result["risk_tier"] == "high"  # exact hit forces high risk -> approval gate


@pytest.mark.asyncio
async def test_screening_node_no_hit_leaves_rules_untouched(settings: Settings) -> None:
    rules = [
        {"rule_id": "AML-001", "title": "x", "category": "reporting", "clause": "y", "score": 0.3}
    ]
    state: CaseState = {
        "case_id": "c-2",
        "case_text": "Routine payroll deposit from a long-standing employer.",
        "retrieved_rules": rules,
    }
    result = await scr.sanctions_screening_node(state)
    assert result["sanctions_hits"] == []
    assert [r["rule_id"] for r in result["retrieved_rules"]] == ["AML-001"]

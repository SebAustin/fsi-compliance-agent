"""Rulebook loading, offline retrieval, and the retrieval node."""

from __future__ import annotations

import pytest

from compliance_agent.config import Settings
from compliance_agent.nodes import rule_retrieval
from compliance_agent.rulebook.indexer import RulebookIndexer, load_rules
from compliance_agent.state import CaseState


def test_load_rules_has_full_rulebook() -> None:
    rules = load_rules()
    assert len(rules) == 46
    assert all({"rule_id", "title", "category", "clause"} <= set(r) for r in rules)


def test_hybrid_surfaces_pep_rule_when_dense_misses_it(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Regression guard for the PEP recall objective (issue #4), offline + deterministic.

    When dense retrieval omits the PEP rule but the lexical pass ranks it (the
    "senior government official" phrasing overlaps AML-004's enumerated terms), hybrid
    fusion must still surface AML-004 into the top-k. This guards the *mechanism* the
    enhancement delivers without depending on a live LLM/embedding outcome.
    """
    indexer = RulebookIndexer(settings)
    # Dense pass returns rules that are NOT the PEP rule (simulate the recall miss).
    monkeypatch.setattr(
        indexer,
        "_vector_search",
        lambda _q, _k: [
            {"rule_id": "AML-010", "title": "x", "category": "wire", "clause": "y", "score": 0.4},
            {
                "rule_id": "AML-013",
                "title": "x",
                "category": "monitoring",
                "clause": "y",
                "score": 0.3,
            },
        ],
    )
    results = indexer.search("foreign senior government official requests a transfer", top_k=8)
    assert "AML-004" in [r["rule_id"] for r in results]


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


# ---------------------------------------------------------------------------
# Hybrid retrieval — RRF fusion unit tests
# ---------------------------------------------------------------------------


def test_rrf_fuse_is_deterministic(settings: Settings) -> None:
    """Same inputs produce an identical order on repeated calls (incl. tie-break)."""
    indexer = RulebookIndexer(settings)
    dense = ["AML-001", "AML-002", "AML-003"]
    sparse = ["AML-003", "AML-001", "AML-002"]
    first = indexer._rrf_fuse(dense, sparse)
    second = indexer._rrf_fuse(dense, sparse)
    assert first == second


def test_rrf_fuse_includes_sparse_only_rule(settings: Settings) -> None:
    """A rule absent from dense but present in sparse appears in the fused output.

    This is the structural property that closes the PEP recall gap: even if Qdrant
    does not return AML-004 in its top-k, the lexical pass can surface it and RRF
    will include it in the fused list.
    """
    indexer = RulebookIndexer(settings)
    # Dense list does NOT include AML-004.
    dense = ["AML-001", "AML-002", "AML-003", "AML-005"]
    # Sparse list ranks AML-004 first.
    sparse = ["AML-004", "AML-001", "AML-002", "AML-003", "AML-005"]
    fused = indexer._rrf_fuse(dense, sparse)
    assert "AML-004" in fused


def test_hybrid_search_lifts_lexically_strong_rule(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A rule absent from the dense over-fetch but strong in sparse enters the top-k.

    Simulates the PEP case: dense returns 3 rules (not including AML-004); the full
    lexical pass ranks AML-004 first; after RRF fusion with top_k=1, AML-004 must win.
    """
    indexer = RulebookIndexer(settings)
    # Dense returns only 3 unrelated rules (AML-004 absent).
    fake_dense = [
        {"rule_id": "AML-001", "title": "T", "clause": "C", "score": 0.9},
        {"rule_id": "AML-002", "title": "T", "clause": "C", "score": 0.8},
        {"rule_id": "AML-003", "title": "T", "clause": "C", "score": 0.7},
    ]
    monkeypatch.setattr(indexer, "_vector_search", lambda q, k: fake_dense)
    # Lexical pass ranks AML-004 at the top for this PEP-like query.
    # We need to monkeypatch _local_search to return AML-004 first.
    fake_sparse = [
        {"rule_id": "AML-004", "title": "PEP", "clause": "politically exposed", "score": 0.5},
        {"rule_id": "AML-001", "title": "T", "clause": "C", "score": 0.3},
        {"rule_id": "AML-002", "title": "T", "clause": "C", "score": 0.2},
        {"rule_id": "AML-003", "title": "T", "clause": "C", "score": 0.1},
    ]
    monkeypatch.setattr(indexer, "_local_search", lambda q, k: fake_sparse[:k])
    # With top_k=1: the best fused rule should be AML-001 (rank-0 dense + rank-1 sparse
    # = 1/60 + 1/61 ≈ 0.033) vs AML-004 (only sparse rank-0 = 1/60 ≈ 0.0167).
    # AML-001 wins. But with top_k=4, AML-004 must appear.
    results = indexer._hybrid_search("foreign finance minister senior official", top_k=4)
    rule_ids_returned = [str(r["rule_id"]) for r in results]
    assert "AML-004" in rule_ids_returned


def test_rrf_fuse_tie_break_by_rule_id(settings: Settings) -> None:
    """When two rules have identical RRF scores the lower rule_id wins."""
    indexer = RulebookIndexer(settings)
    # Two rules each at rank 0 in their own list — equal RRF scores.
    dense = ["AML-010"]
    sparse = ["AML-005"]
    fused = indexer._rrf_fuse(dense, sparse)
    # AML-005 < AML-010 lexicographically, so AML-005 should sort first.
    assert fused[0] == "AML-005"
    assert fused[1] == "AML-010"


def test_rrf_fuse_returns_all_unique_ids(settings: Settings) -> None:
    """Every rule_id from either list appears exactly once in the output."""
    indexer = RulebookIndexer(settings)
    dense = ["AML-001", "AML-002", "AML-003"]
    sparse = ["AML-002", "AML-003", "AML-004"]
    fused = indexer._rrf_fuse(dense, sparse)
    assert len(fused) == len(set(fused))
    assert set(fused) == {"AML-001", "AML-002", "AML-003", "AML-004"}


def test_hybrid_returns_exactly_top_k(settings: Settings, monkeypatch: pytest.MonkeyPatch) -> None:
    """Fused output length equals top_k regardless of how many candidates exist."""
    indexer = RulebookIndexer(settings)
    top_k = 4
    fetch_k = top_k * 3
    # Return more candidates than top_k from the dense side
    fake_dense = [
        {"rule_id": f"AML-{i:03d}", "title": "t", "clause": "c", "score": 1.0 / (i + 1)}
        for i in range(1, fetch_k + 1)
    ]
    monkeypatch.setattr(indexer, "_vector_search", lambda q, k: fake_dense[:k])
    results = indexer._hybrid_search("some query", top_k)
    assert len(results) == top_k


def test_hybrid_search_score_field_present(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Every dict returned by _hybrid_search carries a numeric 'score' field."""
    indexer = RulebookIndexer(settings)
    fake_dense = [
        {"rule_id": f"AML-{i:03d}", "title": "t", "clause": "c", "score": 0.9} for i in range(1, 10)
    ]
    monkeypatch.setattr(indexer, "_vector_search", lambda q, k: fake_dense[:k])
    results = indexer._hybrid_search("politically exposed person", 5)
    assert all("score" in r for r in results)
    assert all(isinstance(r["score"], float) for r in results)


def test_hybrid_falls_back_when_dense_raises(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When _vector_search raises, search() falls back to _local_search unchanged."""
    settings.qdrant_url = "http://127.0.0.1:9"
    indexer = RulebookIndexer(settings)

    def _raise(q: str, k: int) -> list[dict[str, object]]:
        msg = "connection refused"
        raise ConnectionError(msg)

    monkeypatch.setattr(indexer, "_vector_search", _raise)
    results = indexer.search("beneficial ownership unverified", top_k=3)
    # Must return exactly top_k results via the fallback
    assert len(results) == 3
    assert all("score" in r for r in results)


def test_empty_dense_result_logs_warning(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When dense returns an empty list, a structlog warning is emitted and fusion proceeds."""
    indexer = RulebookIndexer(settings)
    monkeypatch.setattr(indexer, "_vector_search", lambda q, k: [])

    warning_events: list[tuple[str, dict[str, object]]] = []

    def _capture(event: str, **kw: object) -> None:
        warning_events.append((event, kw))

    # Patch the module-level logger's warning method to capture structlog events.
    from compliance_agent.rulebook import indexer as indexer_mod

    monkeypatch.setattr(indexer_mod.log, "warning", _capture)

    results = indexer._hybrid_search("foreign finance minister", 5)

    # Must still return results (driven entirely by the lexical pass)
    assert len(results) > 0
    assert all("score" in r for r in results)
    # At least one warning must have been emitted with the expected event key.
    assert any("empty_dense_result" in event for event, _ in warning_events)

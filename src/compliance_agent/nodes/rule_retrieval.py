"""Rule-retrieval node — find the rulebook clauses that apply to a case."""

from __future__ import annotations

import structlog

from compliance_agent.rulebook.indexer import RulebookIndexer
from compliance_agent.state import CaseState

log = structlog.get_logger(__name__)

TOP_K = 5

# Module-level singleton so the rulebook is loaded once, not per case.
_indexer: RulebookIndexer | None = None


def _get_indexer() -> RulebookIndexer:
    global _indexer  # noqa: PLW0603 - intentional process-wide cache
    if _indexer is None:
        _indexer = RulebookIndexer()
    return _indexer


async def rule_retrieval_node(state: CaseState) -> CaseState:
    """Retrieve the top-k applicable rule clauses for the case."""
    indexer = _get_indexer()
    rules = indexer.search(state["case_text"], top_k=TOP_K)
    log.info(
        "retrieval.complete",
        case_id=state["case_id"],
        rule_ids=[r.get("rule_id") for r in rules],
    )
    return {**state, "retrieved_rules": rules}

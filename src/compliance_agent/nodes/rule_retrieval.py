"""Rule-retrieval node — find the rulebook clauses that apply to a case."""

from __future__ import annotations

import structlog

from compliance_agent.audit.recorder import record
from compliance_agent.rulebook.indexer import RulebookIndexer
from compliance_agent.state import CaseState

log = structlog.get_logger(__name__)

# Top-k for rule retrieval. 8 (not 5) gives on-point rules headroom to surface when
# the case vocabulary differs from the clause wording (e.g. PEP synonyms), at a small
# extra determination-context cost.
TOP_K = 8

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
    rule_ids = [str(r.get("rule_id", "")) for r in rules]
    log.info("retrieval.complete", case_id=state["case_id"], rule_ids=rule_ids)
    record(state["case_id"], "rule_retrieval", "retrieved", rule_ids=rule_ids)
    return {**state, "retrieved_rules": rules}

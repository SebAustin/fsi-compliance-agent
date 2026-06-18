"""Sanctions-screening node — deterministic watchlist name-match.

Runs after retrieval and before the determination. Screens the case text against the
synthetic watchlist; on any hit it guarantees the sanctions rules (AML-007 exact-match
handling, AML-046 name-match screening) are in the retrieved set so the determination
can cite them, and records the hits on the state for the determination prompt.
"""

from __future__ import annotations

import structlog

from compliance_agent.audit.recorder import record
from compliance_agent.config import get_settings
from compliance_agent.rulebook.indexer import load_rules
from compliance_agent.sanctions import load_watchlist, screen_text
from compliance_agent.state import CaseState

log = structlog.get_logger(__name__)

# Rules that must be available to cite when a watchlist hit is present.
_SANCTIONS_RULE_IDS = ("AML-046", "AML-007")

_watchlist: list[dict[str, object]] | None = None


def _get_watchlist() -> list[dict[str, object]]:
    global _watchlist  # noqa: PLW0603 - process-wide cache
    if _watchlist is None:
        _watchlist = load_watchlist()
    return _watchlist


def _ensure_sanctions_rules(retrieved: list[dict[str, object]]) -> list[dict[str, object]]:
    """Prepend the sanctions rules if a hit means they must be citable."""
    present = {str(r.get("rule_id")) for r in retrieved}
    missing = [rid for rid in _SANCTIONS_RULE_IDS if rid not in present]
    if not missing:
        return retrieved
    by_id = {r["rule_id"]: r for r in load_rules()}
    injected = [{**by_id[rid], "score": 1.0} for rid in missing if rid in by_id]
    return injected + retrieved


async def sanctions_screening_node(state: CaseState) -> CaseState:
    """Screen the case against the watchlist; surface hits and citable rules."""
    settings = get_settings()
    hits = screen_text(state["case_text"], _get_watchlist(), settings.sanctions_fuzzy_threshold)
    hit_data = [h.model_dump() for h in hits]

    new_state: CaseState = {**state, "sanctions_hits": hit_data}
    if hits:
        new_state["retrieved_rules"] = _ensure_sanctions_rules(
            list(state.get("retrieved_rules", []))
        )
    # An exact watchlist match is the highest-risk event — force high risk so the
    # resulting flag is routed through the human approval gate, never auto-closed.
    if any(h.match_type == "exact" for h in hits):
        new_state["risk_tier"] = "high"

    summary = (
        f"{len(hits)} hit(s): " + ", ".join(f"{h.match_type}:{h.watchlist_id}" for h in hits)
        if hits
        else "no hits"
    )
    log.info("sanctions.screened", case_id=state["case_id"], hits=summary)
    record(state["case_id"], "sanctions_screening", summary)
    return new_state

"""Determination node — the compliance core.

Calls Sonnet 4.6 with the retrieved rule clauses passed as Citations API documents
(citations enabled). Parses a Determination (decision, rationale, confidence,
citations). If a compliant/flag decision carries zero citations it raises
``CitationContractError`` — in compliance you cannot decide on an uncited basis.

The LLM call is isolated in ``_determine_llm`` so tests can mock the boundary; the
contract enforcement lives in the node itself so it is exercised by every path.
"""

from __future__ import annotations

import json
import re
from typing import TYPE_CHECKING, Any, cast

import structlog

from compliance_agent import providers
from compliance_agent.config import Settings, get_settings
from compliance_agent.nodes.exceptions import CitationContractError
from compliance_agent.state import CaseState, CitedRule, Determination

if TYPE_CHECKING:
    from collections.abc import Sequence

log = structlog.get_logger(__name__)

_DECISIONS_REQUIRING_CITATION: frozenset[str] = frozenset({"compliant", "flag"})
_JSON_RE = re.compile(r"\{[^{}]*\"decision\"[^{}]*\}", re.DOTALL)

_CLEARANCE_GUIDANCE = (
    "EVERY determination must cite at least one rule clause — including 'compliant'. "
    "To clear a case as compliant, cite the rule(s) you evaluated whose conditions "
    "are NOT met (for example, the reporting-threshold rule the amount falls below, "
    "or a clearance / safe-harbor clause for routine expected activity) and explain "
    "in your rationale why each cited rule is not triggered. Decide 'needs_review' "
    "only when no provided rule is even relevant to the case."
)

_SYSTEM = (
    "You are a compliance analyst. Using ONLY the provided rule clauses, determine "
    "whether the case is 'compliant', should be 'flag'ged, or 'needs_review'. "
    f"{_CLEARANCE_GUIDANCE} After your analysis, output a single JSON object on its "
    'own line of the form {"decision": "...", "confidence": 0.0} where confidence is '
    "your calibrated probability (0.0-1.0) that the decision is correct."
)

# OpenAI has no native Citations API, so we ask for quoted spans and verify each
# quote against the cited clause ourselves (see _verify_citations).
_SYSTEM_OPENAI = (
    "You are a compliance analyst. Using ONLY the provided rule clauses, determine "
    "whether the case is compliant, should be flagged, or needs review. "
    f"{_CLEARANCE_GUIDANCE} You MUST support a 'compliant' or 'flag' decision by "
    "quoting the exact text of the rule clause(s) you relied on. Respond with ONLY a "
    'JSON object of the form: {"decision": "compliant|flag|needs_review", '
    '"confidence": 0.0, "rationale": "...", "citations": [{"rule_id": "AML-XXX", '
    '"cited_text": "verbatim substring copied from that rule clause"}]}. '
    "Each cited_text MUST be an exact, verbatim substring of the referenced clause."
)


def _build_documents(retrieved_rules: Sequence[dict[str, object]]) -> list[dict[str, object]]:
    """Wrap each retrieved clause as a citations-enabled document block."""
    return [
        {
            "type": "document",
            "source": {
                "type": "text",
                "media_type": "text/plain",
                "data": str(rule.get("clause", "")),
            },
            "title": str(rule.get("rule_id", "")),
            "citations": {"enabled": True},
        }
        for rule in retrieved_rules
    ]


def _parse_decision_json(text: str) -> tuple[str, float]:
    match = _JSON_RE.search(text)
    if not match:
        return "needs_review", 0.0
    payload = json.loads(match.group(0))
    decision = str(payload.get("decision", "needs_review"))
    confidence = float(payload.get("confidence", 0.0))
    return decision, max(0.0, min(1.0, confidence))


def _verify_citations(
    raw_citations: Sequence[dict[str, Any]],
    retrieved_rules: Sequence[dict[str, object]],
) -> list[dict[str, object]]:
    """Keep only citations whose quote is a verbatim substring of the cited clause.

    This is how the OpenAI path upholds the citation contract without a native
    Citations API: a quote the model did not actually take from the clause is
    unverifiable and is dropped, computing exact char offsets for the rest.
    """
    clause_by_id = {str(r.get("rule_id", "")): str(r.get("clause", "")) for r in retrieved_rules}
    verified: list[dict[str, object]] = []
    for cite in raw_citations:
        rule_id = str(cite.get("rule_id", ""))
        quote = str(cite.get("cited_text", ""))
        clause = clause_by_id.get(rule_id)
        if not clause or not quote:
            continue
        start = clause.find(quote)
        if start < 0:
            log.warning("determination.unverifiable_citation", rule_id=rule_id, quote=quote)
            continue
        verified.append(
            {
                "rule_id": rule_id,
                "cited_text": quote,
                "start_char": start,
                "end_char": start + len(quote),
            }
        )
    return verified


def _determine_openai(
    case_text: str,
    retrieved_rules: Sequence[dict[str, object]],
    settings: Settings,
) -> dict[str, object]:
    """Call OpenAI with structured output; verify quoted citations against clauses."""
    rules_block = "\n\n".join(
        f"[{r.get('rule_id', '')}] {r.get('clause', '')}" for r in retrieved_rules
    )
    user = f"RULE CLAUSES:\n{rules_block}\n\nCASE:\n{case_text}"
    text = providers.openai_chat(
        settings,
        settings.openai_determination_model,
        _SYSTEM_OPENAI,
        user,
        json_mode=True,
        max_tokens=1024,
    )
    payload = json.loads(text)
    citations = _verify_citations(payload.get("citations", []), retrieved_rules)
    return {
        "decision": str(payload.get("decision", "needs_review")),
        "rationale": str(payload.get("rationale", "")),
        "confidence": max(0.0, min(1.0, float(payload.get("confidence", 0.0)))),
        "citations": citations,
    }


def _determine_llm(
    case_text: str,
    retrieved_rules: Sequence[dict[str, object]],
    settings: Settings,
) -> dict[str, object]:
    """Dispatch to the configured provider. Returns a raw determination dict."""
    if settings.llm_provider == "openai":
        return _determine_openai(case_text, retrieved_rules, settings)
    return _determine_anthropic(case_text, retrieved_rules, settings)


def _determine_anthropic(
    case_text: str,
    retrieved_rules: Sequence[dict[str, object]],
    settings: Settings,
) -> dict[str, object]:
    """Call Sonnet with the native Citations API enabled."""
    import anthropic

    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
    documents = _build_documents(retrieved_rules)
    content: list[Any] = [*documents, {"type": "text", "text": case_text}]
    message = client.messages.create(
        model=settings.sonnet_model,
        max_tokens=1024,
        temperature=0.0,
        system=_SYSTEM,
        messages=[{"role": "user", "content": content}],
    )

    rationale_parts: list[str] = []
    citations: list[dict[str, object]] = []
    for block in message.content:
        if block.type != "text":
            continue
        rationale_parts.append(block.text)
        for cite in getattr(block, "citations", None) or []:
            doc_index = getattr(cite, "document_index", 0)
            rule_id = (
                str(retrieved_rules[doc_index].get("rule_id", ""))
                if (0 <= doc_index < len(retrieved_rules))
                else getattr(cite, "document_title", "")
            )
            citations.append(
                {
                    "rule_id": rule_id,
                    "cited_text": getattr(cite, "cited_text", ""),
                    "start_char": getattr(cite, "start_char_index", 0),
                    "end_char": getattr(cite, "end_char_index", 0),
                }
            )

    rationale = "".join(rationale_parts)
    decision, confidence = _parse_decision_json(rationale)
    return {
        "decision": decision,
        "rationale": rationale,
        "confidence": confidence,
        "citations": citations,
    }


def _to_determination(raw: dict[str, object]) -> Determination:
    raw_citations = cast("list[dict[str, Any]]", raw.get("citations", []))
    cites = [
        CitedRule(
            rule_id=str(c["rule_id"]),
            cited_text=str(c["cited_text"]),
            start_char=int(c["start_char"]),
            end_char=int(c["end_char"]),
        )
        for c in raw_citations
    ]
    return Determination(
        decision=cast("Any", raw["decision"]),
        rationale=str(raw["rationale"]),
        confidence=float(cast("Any", raw["confidence"])),
        citations=cites,
    )


async def determination_node(state: CaseState) -> CaseState:
    """Produce a cited determination; reject uncited compliant/flag decisions."""
    settings = get_settings()
    retrieved = state.get("retrieved_rules", [])
    raw = _determine_llm(state["case_text"], retrieved, settings)
    determination = _to_determination(raw)

    if determination.decision in _DECISIONS_REQUIRING_CITATION and not determination.citations:
        log.error(
            "determination.uncited",
            case_id=state["case_id"],
            decision=determination.decision,
        )
        raise CitationContractError(
            f"Decision '{determination.decision}' for case {state['case_id']} has no "
            "citation; an uncited determination is invalid in compliance."
        )

    log.info(
        "determination.complete",
        case_id=state["case_id"],
        decision=determination.decision,
        confidence=determination.confidence,
        rule_ids=[c.rule_id for c in determination.citations],
    )
    return {**state, "determination": determination}

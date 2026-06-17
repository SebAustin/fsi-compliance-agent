"""Triage node — classify case type and risk tier with Haiku 4.5.

Output is a strict JSON object {case_type, risk_tier}. The LLM call is isolated in
``_triage_llm`` so tests can mock the network boundary.
"""

from __future__ import annotations

import json
from typing import get_args

import structlog

from compliance_agent import providers
from compliance_agent.audit.recorder import record
from compliance_agent.config import Settings, get_settings
from compliance_agent.state import CaseState, RiskTier

log = structlog.get_logger(__name__)

_VALID_TIERS: frozenset[str] = frozenset(get_args(RiskTier))

_SYSTEM = (
    "You are a compliance triage analyst at a financial institution. Classify the "
    "case into a short case_type and a risk_tier. risk_tier must be exactly one of "
    "'low', 'medium', or 'high'. Structuring, sanctions, PEP, and unverified "
    "beneficial-ownership patterns are high risk. Routine, low-value, well-known "
    "counterparties are low risk. Respond with ONLY a JSON object of the form "
    '{"case_type": "...", "risk_tier": "..."} and nothing else.'
)


def _triage_llm(case_text: str, settings: Settings) -> dict[str, str]:
    """Call the configured provider for triage. Returns {case_type, risk_tier}."""
    if settings.llm_provider == "openai":
        text = providers.openai_chat(
            settings,
            settings.openai_triage_model,
            _SYSTEM,
            case_text,
            json_mode=True,
            max_tokens=256,
        )
    else:
        text = providers.anthropic_chat(
            settings, settings.haiku_model, _SYSTEM, case_text, max_tokens=256
        )
    parsed: dict[str, str] = json.loads(text)
    return parsed


def _coerce_tier(value: str) -> RiskTier:
    tier = value.strip().lower()
    if tier not in _VALID_TIERS:
        log.warning("triage.invalid_tier", received=value, defaulting_to="high")
        return "high"  # fail safe: unknown tier escalates, never under-classifies
    return tier  # type: ignore[return-value]


async def triage_node(state: CaseState) -> CaseState:
    """Classify case_type and risk_tier, writing both into state."""
    settings = get_settings()
    result = _triage_llm(state["case_text"], settings)
    case_type = str(result.get("case_type", "unknown")).strip() or "unknown"
    risk_tier = _coerce_tier(str(result.get("risk_tier", "high")))
    log.info(
        "triage.classified",
        case_id=state["case_id"],
        case_type=case_type,
        risk_tier=risk_tier,
    )
    record(state["case_id"], "triage", f"{case_type} / risk={risk_tier}")
    return {**state, "case_type": case_type, "risk_tier": risk_tier}

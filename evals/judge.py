"""LLM judge — scores whether a determination's rationale is sound.

Uses the configured provider's strongest model (OpenAI gpt-4.1 or Anthropic Opus).
Given the case and the determination rationale, returns a quality score in [0, 1].
The call is isolated so it can be mocked in tests; without an API key for the active
provider it returns a neutral 0.5 and logs, rather than silently inflating the metric.
"""

from __future__ import annotations

import re

import structlog

from compliance_agent import providers
from compliance_agent.config import get_settings

log = structlog.get_logger(__name__)

_SCORE_RE = re.compile(r"0?\.\d+|[01](?:\.0+)?")

_SYSTEM = (
    "You are a senior compliance reviewer auditing an AI determination. Given the "
    "case and the analyst's rationale, rate how sound and well-grounded the "
    "reasoning is from 0.0 (unsupported) to 1.0 (fully grounded in the rules). "
    "Respond with ONLY the number."
)


async def judge_determination(case_text: str, rationale: str) -> float:
    """Return a [0, 1] quality score for a determination rationale."""
    settings = get_settings()
    if not settings.active_llm_key():
        log.warning("judge.no_api_key", provider=settings.llm_provider, fallback=0.5)
        return 0.5

    user = f"CASE:\n{case_text}\n\nRATIONALE:\n{rationale}"
    if settings.llm_provider == "openai":
        text = await providers.openai_chat_async(
            settings, settings.openai_judge_model, _SYSTEM, user, max_tokens=16
        )
    else:
        text = await providers.anthropic_chat_async(
            settings, settings.judge_model, _SYSTEM, user, max_tokens=16
        )

    match = _SCORE_RE.search(text)
    if not match:
        log.warning("judge.unparseable", raw=text, fallback=0.5)
        return 0.5
    return max(0.0, min(1.0, float(match.group(0))))

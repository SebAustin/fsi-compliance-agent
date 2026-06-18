"""Provider abstraction over OpenAI and Anthropic.

The compliance graph is provider-agnostic: nodes call these helpers and dispatch on
``settings.llm_provider`` / ``settings.embed_provider``. OpenAI is the default.

Note on citations: Anthropic exposes a native Citations API that returns verifiable
char offsets into the source document. OpenAI has no equivalent, so for the OpenAI
path the determination node asks for quoted spans via structured output and verifies
each quote by locating it inside the cited rule clause (see determination.py). Either
way, an unverifiable citation is dropped and an uncited compliant/flag decision is
rejected — the citation contract holds across providers.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Sequence

    from compliance_agent.config import Settings

# --- cost tracking ---------------------------------------------------------------
# USD per 1M tokens (input, output). ESTIMATE for reporting only — update as vendor
# pricing changes; embeddings bill input only.
_PRICE_PER_MTOK: dict[str, tuple[float, float]] = {
    "gpt-4.1": (2.0, 8.0),
    "gpt-4.1-mini": (0.4, 1.6),
    "text-embedding-3-large": (0.13, 0.0),
    "claude-sonnet-4-6": (3.0, 15.0),
    "claude-haiku-4-5-20250929": (1.0, 5.0),
    "claude-opus-4-7": (15.0, 75.0),
}

_cost_usd = 0.0


def reset_cost() -> None:
    """Reset the accumulated cost counter (call at the start of an eval run)."""
    global _cost_usd  # noqa: PLW0603 - process-wide accumulator
    _cost_usd = 0.0


def total_cost_usd() -> float:
    """Estimated USD spent since the last reset."""
    return _cost_usd


def _record_cost(model: str, input_tokens: int, output_tokens: int) -> None:
    global _cost_usd  # noqa: PLW0603 - process-wide accumulator
    in_price, out_price = _PRICE_PER_MTOK.get(model, (0.0, 0.0))
    _cost_usd += input_tokens / 1e6 * in_price + output_tokens / 1e6 * out_price


# --- chat (sync) -----------------------------------------------------------------


def openai_chat(
    settings: Settings,
    model: str,
    system: str,
    user: str,
    *,
    json_mode: bool = False,
    max_tokens: int = 1024,
) -> str:
    """Single-turn OpenAI chat completion; returns the message text."""
    from openai import OpenAI

    client = OpenAI(api_key=settings.openai_api_key)
    kwargs: dict[str, Any] = {}
    if json_mode:
        kwargs["response_format"] = {"type": "json_object"}
    response = client.chat.completions.create(
        model=model,
        temperature=0.0,
        max_tokens=max_tokens,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        **kwargs,
    )
    usage = response.usage
    if usage is not None:
        _record_cost(model, usage.prompt_tokens, usage.completion_tokens)
    return response.choices[0].message.content or ""


def anthropic_chat(
    settings: Settings,
    model: str,
    system: str,
    user: str,
    *,
    max_tokens: int = 1024,
) -> str:
    """Single-turn Anthropic message; returns concatenated text blocks."""
    import anthropic

    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
    message = client.messages.create(
        model=model,
        max_tokens=max_tokens,
        temperature=0.0,
        system=system,
        messages=[{"role": "user", "content": user}],
    )
    _record_cost(model, message.usage.input_tokens, message.usage.output_tokens)
    return "".join(block.text for block in message.content if block.type == "text")


# --- chat (async, used by the eval judge) ----------------------------------------


async def openai_chat_async(
    settings: Settings, model: str, system: str, user: str, *, max_tokens: int = 64
) -> str:
    """Async OpenAI chat completion."""
    from openai import AsyncOpenAI

    client = AsyncOpenAI(api_key=settings.openai_api_key)
    response = await client.chat.completions.create(
        model=model,
        temperature=0.0,
        max_tokens=max_tokens,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    )
    usage = response.usage
    if usage is not None:
        _record_cost(model, usage.prompt_tokens, usage.completion_tokens)
    return response.choices[0].message.content or ""


async def anthropic_chat_async(
    settings: Settings, model: str, system: str, user: str, *, max_tokens: int = 64
) -> str:
    """Async Anthropic message."""
    import anthropic

    client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
    message = await client.messages.create(
        model=model,
        max_tokens=max_tokens,
        temperature=0.0,
        system=system,
        messages=[{"role": "user", "content": user}],
    )
    _record_cost(model, message.usage.input_tokens, message.usage.output_tokens)
    return "".join(block.text for block in message.content if block.type == "text")


# --- embeddings ------------------------------------------------------------------


def embed_texts(settings: Settings, texts: Sequence[str]) -> list[list[float]]:
    """Embed texts with the configured provider at ``settings.embed_dim``."""
    if settings.embed_provider == "openai":
        from openai import OpenAI

        client = OpenAI(api_key=settings.openai_api_key)
        response = client.embeddings.create(
            model=settings.openai_embed_model,
            input=list(texts),
            dimensions=settings.embed_dim,
        )
        if response.usage is not None:
            _record_cost(settings.openai_embed_model, response.usage.prompt_tokens, 0)
        return [list(item.embedding) for item in response.data]

    import voyageai

    voyage_client = voyageai.Client(api_key=settings.voyage_api_key)  # type: ignore[attr-defined]
    result = voyage_client.embed(
        list(texts),
        model=settings.voyage_embed_model,
        output_dimension=settings.embed_dim,
    )
    return [list(vec) for vec in result.embeddings]

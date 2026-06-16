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
        return [list(item.embedding) for item in response.data]

    import voyageai

    voyage_client = voyageai.Client(api_key=settings.voyage_api_key)  # type: ignore[attr-defined]
    result = voyage_client.embed(
        list(texts),
        model=settings.voyage_embed_model,
        output_dimension=settings.embed_dim,
    )
    return [list(vec) for vec in result.embeddings]

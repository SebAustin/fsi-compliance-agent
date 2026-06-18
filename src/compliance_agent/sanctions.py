"""Deterministic sanctions watchlist screening (exact + fuzzy name match).

Real sanctions screening is deterministic list-matching, not model judgment — so this
runs independently of the LLM and feeds its result into the determination. An exact
match must block/flag; a fuzzy near-match must go to human review (a false hit is cheap
to clear, a missed true hit is the violation).

The watchlist is synthetic and originally authored (fictional names); see
rulebook/watchlist.jsonl.
"""

from __future__ import annotations

import json
import re
from difflib import SequenceMatcher
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict

WATCHLIST_PATH = Path(__file__).parent / "rulebook" / "watchlist.jsonl"
_NON_ALNUM = re.compile(r"[^a-z0-9\s]")
_WS = re.compile(r"\s+")

MatchType = Literal["exact", "fuzzy"]


class SanctionsHit(BaseModel):
    """A watchlist match found in a case."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    watchlist_id: str
    matched_name: str
    matched_text: str
    match_type: MatchType
    score: float


def load_watchlist(path: Path = WATCHLIST_PATH) -> list[dict[str, object]]:
    """Load the synthetic sanctions watchlist."""
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def normalize(text: str) -> str:
    """Lowercase, strip punctuation, collapse whitespace for name comparison."""
    return _WS.sub(" ", _NON_ALNUM.sub(" ", text.lower())).strip()


def _names_for(entry: dict[str, object]) -> list[str]:
    aliases = entry.get("aliases")
    alias_list = aliases if isinstance(aliases, list) else []
    return [str(entry["name"]), *[str(a) for a in alias_list]]


def _best_window_ratio(norm_name: str, text_tokens: list[str]) -> tuple[float, str]:
    width = len(norm_name.split())
    best_score = 0.0
    best_span = ""
    for i in range(len(text_tokens) - width + 1):
        window = " ".join(text_tokens[i : i + width])
        score = SequenceMatcher(None, norm_name, window).ratio()
        if score > best_score:
            best_score, best_span = score, window
    return best_score, best_span


def screen_text(
    text: str,
    watchlist: list[dict[str, object]],
    fuzzy_threshold: float = 0.85,
) -> list[SanctionsHit]:
    """Screen free text against the watchlist. Exact matches first, else best fuzzy.

    Returns at most one hit per watchlist entry (the strongest match across its names).
    """
    norm_text = normalize(text)
    text_tokens = norm_text.split()
    hits: list[SanctionsHit] = []

    for entry in watchlist:
        wl_id = str(entry["id"])
        exact_hit: SanctionsHit | None = None
        best_fuzzy: SanctionsHit | None = None

        for name in _names_for(entry):
            norm_name = normalize(name)
            if not norm_name:
                continue
            if norm_name in norm_text:
                exact_hit = SanctionsHit(
                    watchlist_id=wl_id,
                    matched_name=name,
                    matched_text=norm_name,
                    match_type="exact",
                    score=1.0,
                )
                break
            score, span = _best_window_ratio(norm_name, text_tokens)
            if fuzzy_threshold <= score < 1.0 and (best_fuzzy is None or score > best_fuzzy.score):
                best_fuzzy = SanctionsHit(
                    watchlist_id=wl_id,
                    matched_name=name,
                    matched_text=span,
                    match_type="fuzzy",
                    score=round(score, 3),
                )

        if exact_hit is not None:
            hits.append(exact_hit)
        elif best_fuzzy is not None:
            hits.append(best_fuzzy)

    return hits

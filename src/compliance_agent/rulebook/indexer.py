"""Rulebook indexing and retrieval.

Embeds each rule clause with voyage-3-large (dim 256) and upserts into Qdrant.
``search()`` returns the top-k clauses for a case. When Qdrant or Voyage are
unreachable (local dev, CI, tests) it falls back to a deterministic token-overlap
search so the graph remains runnable end-to-end without external services — the
fallback is logged, never silent.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import TYPE_CHECKING

import structlog

from compliance_agent.config import Settings, get_settings

if TYPE_CHECKING:
    from collections.abc import Sequence

log = structlog.get_logger(__name__)

RULES_PATH = Path(__file__).parent / "rules.jsonl"
_WORD_RE = re.compile(r"[a-z0-9]+")


def load_rules(path: Path = RULES_PATH) -> list[dict[str, str]]:
    """Load the synthetic rulebook from rules.jsonl."""
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def _tokens(text: str) -> set[str]:
    return set(_WORD_RE.findall(text.lower()))


class RulebookIndexer:
    """Builds and queries the rulebook vector index."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self._rules = load_rules()

    # --- embedding + index build -------------------------------------------------

    def _embed(self, texts: Sequence[str]) -> list[list[float]]:
        import voyageai

        client = voyageai.Client(api_key=self.settings.voyage_api_key)  # type: ignore[attr-defined]
        result = client.embed(
            list(texts),
            model=self.settings.embed_model,
            output_dimension=self.settings.embed_dim,
        )
        return [list(vec) for vec in result.embeddings]

    def _qdrant(self) -> object:
        from qdrant_client import QdrantClient

        return QdrantClient(
            url=self.settings.qdrant_url,
            api_key=self.settings.qdrant_api_key or None,
        )

    def build(self) -> int:
        """Embed every rule clause and upsert into Qdrant. Returns rule count."""
        from qdrant_client.models import Distance, PointStruct, VectorParams

        client = self._qdrant()
        vectors = self._embed([r["clause"] for r in self._rules])
        client.recreate_collection(  # type: ignore[attr-defined]
            collection_name=self.settings.qdrant_collection,
            vectors_config=VectorParams(size=self.settings.embed_dim, distance=Distance.COSINE),
        )
        points = [
            PointStruct(id=i, vector=vectors[i], payload=self._rules[i])
            for i in range(len(self._rules))
        ]
        client.upsert(collection_name=self.settings.qdrant_collection, points=points)  # type: ignore[attr-defined]
        log.info("rulebook.indexed", count=len(self._rules))
        return len(self._rules)

    # --- retrieval ---------------------------------------------------------------

    def search(self, query: str, top_k: int = 5) -> list[dict[str, object]]:
        """Return top-k rule payloads with scores for a case description."""
        try:
            return self._vector_search(query, top_k)
        except Exception as exc:  # noqa: BLE001 - fall back, but surface it
            log.warning("rulebook.vector_search_failed", error=str(exc), fallback="token_overlap")
            return self._local_search(query, top_k)

    def _vector_search(self, query: str, top_k: int) -> list[dict[str, object]]:
        client = self._qdrant()
        vector = self._embed([query])[0]
        hits = client.search(  # type: ignore[attr-defined]
            collection_name=self.settings.qdrant_collection,
            query_vector=vector,
            limit=top_k,
        )
        results: list[dict[str, object]] = []
        for hit in hits:
            payload = dict(hit.payload or {})
            payload["score"] = float(hit.score)
            results.append(payload)
        return results

    def _local_search(self, query: str, top_k: int) -> list[dict[str, object]]:
        """Deterministic token-overlap (Jaccard) retrieval for offline use."""
        q_tokens = _tokens(query)
        scored: list[tuple[float, dict[str, str]]] = []
        for rule in self._rules:
            r_tokens = _tokens(f"{rule['title']} {rule['clause']}")
            union = q_tokens | r_tokens
            score = len(q_tokens & r_tokens) / len(union) if union else 0.0
            scored.append((score, rule))
        scored.sort(key=lambda pair: pair[0], reverse=True)
        return [{**rule, "score": score} for score, rule in scored[:top_k]]

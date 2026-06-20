"""Rulebook indexing and retrieval.

Embeds each rule clause with voyage-3-large (dim 256) and upserts into Qdrant.
``search()`` returns the top-k clauses for a case. When Qdrant or Voyage are
unreachable (local dev, CI, tests) it falls back to a deterministic token-overlap
search so the graph remains runnable end-to-end without external services — the
fallback is logged, never silent.

In production (Qdrant reachable), ``search()`` uses hybrid retrieval: dense
candidates are over-fetched at ``top_k * 3``, a lexical Jaccard pass scores the
full rulebook, and the two ranked lists are fused with Reciprocal Rank Fusion
(RRF, Cormack et al. constant ``k=60``) before returning the top-k results.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import TYPE_CHECKING

import structlog

from compliance_agent import providers
from compliance_agent.config import Settings, get_settings

if TYPE_CHECKING:
    from collections.abc import Sequence

log = structlog.get_logger(__name__)

RULES_PATH = Path(__file__).parent / "rules.jsonl"
_WORD_RE = re.compile(r"[a-z0-9]+")

# Cormack et al. default constant for Reciprocal Rank Fusion.
_RRF_K = 60


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
        return providers.embed_texts(self.settings, texts)

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
        collection = self.settings.qdrant_collection
        if client.collection_exists(collection):  # type: ignore[attr-defined]
            client.delete_collection(collection)  # type: ignore[attr-defined]
        client.create_collection(  # type: ignore[attr-defined]
            collection_name=collection,
            vectors_config=VectorParams(size=self.settings.embed_dim, distance=Distance.COSINE),
        )
        points = [
            PointStruct(id=i, vector=vectors[i], payload=self._rules[i])
            for i in range(len(self._rules))
        ]
        client.upsert(collection_name=collection, points=points)  # type: ignore[attr-defined]
        log.info("rulebook.indexed", count=len(self._rules))
        return len(self._rules)

    # --- retrieval ---------------------------------------------------------------

    @staticmethod
    def _rrf_fuse(dense_ids: list[str], sparse_ids: list[str], k: int = _RRF_K) -> list[str]:
        """Return rule_ids ranked by Reciprocal Rank Fusion score.

        Each list contributes ``1 / (k + rank)`` per position (rank starting at 0).
        Ties are broken deterministically by rule_id ascending so that results are
        reproducible across runs — required for a regulated audit artifact.
        """
        fused: dict[str, float] = {}
        for ranked in (dense_ids, sparse_ids):
            for rank, rule_id in enumerate(ranked):
                fused[rule_id] = fused.get(rule_id, 0.0) + 1.0 / (k + rank)
        return sorted(fused, key=lambda rid: (-fused[rid], rid))

    def _hybrid_search(self, query: str, top_k: int) -> list[dict[str, object]]:
        """Over-fetch dense candidates, fuse with a lexical pass via RRF, return top_k.

        Exceptions from ``_vector_search`` propagate to ``search()``'s except clause
        so that the offline fallback fires correctly.  If Qdrant is reachable but
        returns an empty list, a structlog warning is emitted and the fused ranking
        (driven by the lexical pass) is used instead.
        """
        fetch_k = top_k * 3
        dense = self._vector_search(query, fetch_k)  # may raise — let it propagate
        if not dense:
            log.warning("rulebook.empty_dense_result", query=query, fetch_k=fetch_k)
        # Lexical pass always scores the full rulebook (offline, never raises).
        sparse = self._local_search(query, fetch_k)

        dense_ids = [str(r["rule_id"]) for r in dense]
        sparse_ids = [str(r["rule_id"]) for r in sparse]
        fused_ids = self._rrf_fuse(dense_ids, sparse_ids)

        # Build a lookup so we can re-attach full payloads.  Dense payload takes
        # precedence (it carries the original cosine score); sparse fills gaps.
        by_id: dict[str, dict[str, object]] = {}
        for result in (*sparse, *dense):  # dense overwrites sparse — intentional
            by_id[str(result["rule_id"])] = result

        out: list[dict[str, object]] = []
        fused_score: dict[str, float] = {
            rid: sum(
                1.0 / (_RRF_K + rank)
                for ranked in (dense_ids, sparse_ids)
                for rank, r in enumerate(ranked)
                if r == rid
            )
            for rid in fused_ids[:top_k]
        }
        for rule_id in fused_ids[:top_k]:
            payload = {**by_id[rule_id], "score": fused_score[rule_id]}
            out.append(payload)
        return out

    def search(self, query: str, top_k: int = 5) -> list[dict[str, object]]:
        """Return top-k rule payloads with scores for a case description."""
        try:
            return self._hybrid_search(query, top_k)
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

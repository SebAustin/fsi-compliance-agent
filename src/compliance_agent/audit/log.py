"""Hash-chained, append-only audit log — the artifact a regulator examines.

Each entry links to the previous one by hash. ``verify()`` recomputes the chain and
detects any tampering: an edited field, a reordered line, or a deleted entry all
break the chain. This is the product surface for examiner review, so we treat it as
such — append-only writes, deterministic serialization, no in-place mutation.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import TypedDict

GENESIS_HASH = "0" * 64

# Fields covered by the hash, in a fixed order. hash_self is derived, not covered.
_HASHED_FIELDS = (
    "timestamp",
    "case_id",
    "node",
    "decision",
    "rule_ids_cited",
    "confidence",
    "hash_prev",
)


class AuditEntry(TypedDict):
    """One immutable audit record."""

    timestamp: str
    case_id: str
    node: str
    decision: str
    rule_ids_cited: list[str]
    confidence: float | None
    hash_prev: str
    hash_self: str


def _entry_hash(prev: str, hashed: dict[str, object]) -> str:
    payload = json.dumps(hashed, sort_keys=True)
    return hashlib.sha256((prev + payload).encode()).hexdigest()


class AuditLog:
    """Append-only hash-chained audit log backed by a JSONL file.

    ``_cached_last_hash`` keeps the most recent hash in memory so repeated
    ``append()`` calls skip the O(n) file read.  This cache assumes a single
    writer process; ``verify()`` always reads from disk so tamper detection is
    never affected by the cache.
    """

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # Lazily initialised on the first append; None means "not yet read".
        self._cached_last_hash: str | None = None

    def _read_last_hash_from_file(self) -> str:
        """Read the last recorded hash directly from disk (used for lazy init)."""
        if not self.path.exists():
            return GENESIS_HASH
        lines = self.path.read_text().splitlines()
        if not lines:
            return GENESIS_HASH
        return str(json.loads(lines[-1])["hash_self"])

    def _last_hash(self) -> str:
        if self._cached_last_hash is None:
            self._cached_last_hash = self._read_last_hash_from_file()
        return self._cached_last_hash

    def append(
        self,
        case_id: str,
        node: str,
        decision: str,
        rule_ids: list[str] | None = None,
        confidence: float | None = None,
    ) -> str:
        """Append an entry, chaining it to the previous hash. Returns hash_self."""
        prev = self._last_hash()
        hashed: dict[str, object] = {
            "timestamp": datetime.now(UTC).isoformat(),
            "case_id": case_id,
            "node": node,
            "decision": decision,
            "rule_ids_cited": rule_ids or [],
            "confidence": confidence,
            "hash_prev": prev,
        }
        hash_self = _entry_hash(prev, hashed)
        entry: AuditEntry = {**hashed, "hash_self": hash_self}  # type: ignore[typeddict-item]
        with self.path.open("a") as handle:
            handle.write(json.dumps(entry) + "\n")
        # Update in-memory cache so the next append avoids a disk read.
        self._cached_last_hash = hash_self
        return hash_self

    def verify(self) -> bool:
        """Recompute the chain end-to-end; return False on any tampering."""
        if not self.path.exists():
            return True
        prev = GENESIS_HASH
        for line in self.path.read_text().splitlines():
            if not line.strip():
                continue
            entry = json.loads(line)
            if entry["hash_prev"] != prev:
                return False
            hashed = {field: entry[field] for field in _HASHED_FIELDS}
            if entry["hash_self"] != _entry_hash(prev, hashed):
                return False
            prev = entry["hash_self"]
        return True

    def read_case(self, case_id: str) -> list[AuditEntry]:
        """Return the ordered trail for a single case."""
        if not self.path.exists():
            return []
        trail: list[AuditEntry] = []
        for line in self.path.read_text().splitlines():
            if not line.strip():
                continue
            entry = json.loads(line)
            if entry["case_id"] == case_id:
                trail.append(entry)
        return trail

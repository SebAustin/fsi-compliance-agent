"""Audit log: hash chaining and tamper detection."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from compliance_agent.audit.log import AuditLog


def test_append_chains_hashes(audit_path: Path) -> None:
    log = AuditLog(audit_path)
    h1 = log.append("c-1", "triage", "n/a")
    h2 = log.append("c-1", "close", "flag", rule_ids=["AML-002"], confidence=0.9)

    lines = audit_path.read_text().splitlines()
    assert len(lines) == 2
    assert json.loads(lines[1])["hash_prev"] == h1
    assert json.loads(lines[1])["hash_self"] == h2


def test_verify_passes_for_untouched_log(audit_path: Path) -> None:
    log = AuditLog(audit_path)
    for i in range(5):
        log.append(f"c-{i}", "close", "compliant", confidence=0.8)
    assert log.verify() is True


def test_verify_detects_tampered_middle_entry(audit_path: Path) -> None:
    log = AuditLog(audit_path)
    for i in range(5):
        log.append(f"c-{i}", "close", "compliant", confidence=0.8)

    lines = audit_path.read_text().splitlines()
    tampered = json.loads(lines[2])
    tampered["decision"] = "flag"  # change a field without recomputing the hash
    lines[2] = json.dumps(tampered)
    audit_path.write_text("\n".join(lines) + "\n")

    assert log.verify() is False


def test_verify_detects_deleted_entry(audit_path: Path) -> None:
    log = AuditLog(audit_path)
    for i in range(4):
        log.append(f"c-{i}", "close", "compliant", confidence=0.8)

    lines = audit_path.read_text().splitlines()
    del lines[1]  # drop an entry — breaks the chain
    audit_path.write_text("\n".join(lines) + "\n")

    assert log.verify() is False


def test_read_case_returns_only_that_case(audit_path: Path) -> None:
    log = AuditLog(audit_path)
    log.append("c-1", "close", "flag")
    log.append("c-2", "close", "compliant")
    log.append("c-1", "triage", "n/a")

    trail = log.read_case("c-1")
    assert len(trail) == 2
    assert all(entry["case_id"] == "c-1" for entry in trail)


def test_verify_true_on_missing_log(audit_path: Path) -> None:
    assert AuditLog(audit_path).verify() is True


# ---------------------------------------------------------------------------
# In-memory last-hash cache tests
# ---------------------------------------------------------------------------


def test_append_uses_cached_last_hash(audit_path: Path) -> None:
    """After the first append the file-reading helper is not called again."""
    log = AuditLog(audit_path)
    n_appends = 5
    with patch.object(log, "_read_last_hash_from_file", wraps=log._read_last_hash_from_file) as spy:
        for i in range(n_appends):
            log.append(f"c-{i}", "close", "compliant", confidence=0.9)
        # Lazy init reads the file at most once (on the very first call).
        assert spy.call_count <= 1


def test_cached_hash_matches_fresh_disk_read(audit_path: Path) -> None:
    """The in-memory cache returns the same value as a fresh read from disk."""
    log = AuditLog(audit_path)
    for i in range(3):
        log.append(f"c-{i}", "triage", "n/a")
    # Cache should now hold the last hash
    cached = log._cached_last_hash
    # Fresh disk read
    fresh = log._read_last_hash_from_file()
    assert cached == fresh


def test_verify_still_detects_tampering_with_cache(audit_path: Path) -> None:
    """Populating the cache does not let a tampered file pass verify()."""
    log = AuditLog(audit_path)
    for i in range(4):
        log.append(f"c-{i}", "close", "compliant", confidence=0.8)

    # Tamper with the second line on disk
    lines = audit_path.read_text().splitlines()
    tampered = json.loads(lines[1])
    tampered["decision"] = "flag"
    lines[1] = json.dumps(tampered)
    audit_path.write_text("\n".join(lines) + "\n")

    # verify() must read from disk and detect the tampering
    assert log.verify() is False


def test_lazy_init_over_preexisting_file(audit_path: Path) -> None:
    """Opening AuditLog over a file with prior entries chains correctly on append."""
    # Write initial entries with one instance
    log_a = AuditLog(audit_path)
    log_a.append("c-1", "triage", "n/a")
    log_a.append("c-1", "close", "compliant", rule_ids=["AML-041"], confidence=0.95)

    # Open a new instance over the same file (lazy init, cache is None)
    log_b = AuditLog(audit_path)
    assert log_b._cached_last_hash is None  # not yet initialised
    log_b.append("c-2", "close", "flag", rule_ids=["AML-002"], confidence=0.88)

    # The full chain (3 entries) must verify correctly
    assert log_b.verify() is True

"""Audit log: hash chaining and tamper detection."""

from __future__ import annotations

import json
from pathlib import Path

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

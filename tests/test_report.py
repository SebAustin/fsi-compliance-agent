"""Examiner export: per-case Markdown report rendering and the endpoint."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from compliance_agent.api import server
from compliance_agent.audit.log import AuditLog
from compliance_agent.audit.report import render_case_report
from compliance_agent.config import Settings

_RULES = {
    "AML-002": {
        "rule_id": "AML-002",
        "title": "Structuring Prohibition",
        "clause": "No structuring.",
    },
}


def _entries() -> list[dict[str, object]]:
    return [
        {
            "timestamp": "2026-06-17T10:00:00",
            "case_id": "c-1",
            "node": "triage",
            "decision": "structuring / risk=high",
            "rule_ids_cited": [],
            "confidence": None,
            "hash_prev": "0",
            "hash_self": "a",
        },
        {
            "timestamp": "2026-06-17T10:00:01",
            "case_id": "c-1",
            "node": "determination",
            "decision": "flag",
            "rule_ids_cited": ["AML-002"],
            "confidence": 0.91,
            "hash_prev": "a",
            "hash_self": "b",
        },
    ]


def test_report_contains_timeline_and_cited_clause() -> None:
    md = render_case_report("c-1", _entries(), _RULES, integrity_ok=True)  # type: ignore[arg-type]
    assert "# Compliance audit trail — case `c-1`" in md
    assert "VERIFIED" in md
    assert "Determination" in md
    assert "flag" in md
    assert "AML-002 — Structuring Prohibition" in md
    assert "> No structuring." in md  # clause text resolved from the rulebook


def test_report_flags_tampered_chain() -> None:
    md = render_case_report("c-1", _entries(), _RULES, integrity_ok=False)  # type: ignore[arg-type]
    assert "FAILED" in md


def test_report_handles_unknown_rule() -> None:
    entries = _entries()
    entries[1]["rule_ids_cited"] = ["AML-999"]
    md = render_case_report("c-1", entries, _RULES, integrity_ok=True)  # type: ignore[arg-type]
    assert "Rule not found" in md


@pytest.fixture
def client(settings: Settings) -> TestClient:
    return TestClient(server.app)


def test_audit_case_endpoint_returns_markdown(settings: Settings, client: TestClient) -> None:
    audit = AuditLog(Path(settings.audit_log_path))
    audit.append("case-x", "triage", "payroll / risk=low")
    audit.append("case-x", "close", "compliant", rule_ids=["AML-044"], confidence=0.95)

    response = client.get("/audit/case/case-x")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/markdown")
    assert "case `case-x`" in response.text
    assert "Close" in response.text


def test_audit_case_404_for_unknown_case(client: TestClient) -> None:
    response = client.get("/audit/case/does-not-exist")
    assert response.status_code == 404

"""FastAPI surface: review, approvals, audit verify."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from compliance_agent.api import server
from compliance_agent.config import Settings
from compliance_agent.nodes import determination, triage


@pytest.fixture
def client(settings: Settings) -> TestClient:
    return TestClient(server.app)


def test_review_low_risk_compliant(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, settings: Settings
) -> None:
    settings.abstention_threshold = 0.5
    monkeypatch.setattr(
        triage, "_triage_llm", lambda *_: {"case_type": "payroll", "risk_tier": "low"}
    )
    monkeypatch.setattr(
        determination,
        "_determine_llm",
        lambda *_: {
            "decision": "compliant",
            "rationale": "routine",
            "confidence": 0.96,
            "citations": [
                {"rule_id": "AML-001", "cited_text": "x", "start_char": 0, "end_char": 1}
            ],
        },
    )
    response = client.post("/review", json={"case_id": "c-1", "case_text": "payroll deposit"})
    assert response.status_code == 200
    body = response.json()
    assert body["final_decision"] == "compliant"
    assert body["citations"]


def test_audit_verify_endpoint(client: TestClient) -> None:
    response = client.get("/audit/verify")
    assert response.status_code == 200
    assert response.json()["valid"] is True


def test_resolve_approval_endpoint(client: TestClient) -> None:
    response = client.post("/approvals/c-99", json={"action": "approve"})
    assert response.status_code == 200
    assert response.json()["status"] == "approved"


def test_resolve_invalid_action_returns_422(client: TestClient) -> None:
    response = client.post("/approvals/c-99", json={"action": "nope"})
    assert response.status_code == 422


def test_list_approvals_endpoint(client: TestClient) -> None:
    response = client.get("/approvals")
    assert response.status_code == 200
    assert "pending" in response.json()

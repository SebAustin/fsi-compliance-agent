"""Slack interactivity: signature verification, payload parsing, and the endpoint."""

from __future__ import annotations

import json
import time
from urllib.parse import urlencode

import pytest
from fastapi.testclient import TestClient
from slack_sdk.signature import SignatureVerifier

from compliance_agent import slack
from compliance_agent.api import server
from compliance_agent.config import Settings

SECRET = "test-signing-secret"  # noqa: S105 - test-only fixture value


def _interaction_body(case_id: str, action_id: str) -> str:
    payload = {"actions": [{"action_id": action_id, "block_id": f"approval::{case_id}"}]}
    return urlencode({"payload": json.dumps(payload)})


def _signed_headers(body: str) -> dict[str, str]:
    timestamp = str(int(time.time()))
    signature = SignatureVerifier(SECRET).generate_signature(timestamp=timestamp, body=body)
    return {
        "X-Slack-Request-Timestamp": timestamp,
        "X-Slack-Signature": signature,
        "Content-Type": "application/x-www-form-urlencoded",
    }


# --- parse_interaction ----------------------------------------------------------


def test_parse_interaction_extracts_case_and_action() -> None:
    case_id, action = slack.parse_interaction(_interaction_body("c-42", "approve"))
    assert case_id == "c-42"
    assert action == "approve"


def test_parse_interaction_rejects_non_approval_block() -> None:
    body = urlencode(
        {"payload": json.dumps({"actions": [{"action_id": "approve", "block_id": "other::x"}]})}
    )
    with pytest.raises(ValueError, match="unexpected block_id"):
        slack.parse_interaction(body)


def test_parse_interaction_rejects_missing_payload() -> None:
    with pytest.raises(ValueError, match="missing payload"):
        slack.parse_interaction("")


# --- verify_signature -----------------------------------------------------------


def test_verify_signature_valid(settings: Settings) -> None:
    settings.slack_signing_secret = SECRET
    body = _interaction_body("c-1", "approve")
    headers = _signed_headers(body)
    assert slack.verify_signature(
        settings,
        body=body,
        timestamp=headers["X-Slack-Request-Timestamp"],
        signature=headers["X-Slack-Signature"],
    )


def test_verify_signature_rejects_tampered_body(settings: Settings) -> None:
    settings.slack_signing_secret = SECRET
    body = _interaction_body("c-1", "approve")
    headers = _signed_headers(body)
    assert not slack.verify_signature(
        settings,
        body=_interaction_body("c-1", "override"),  # different body, old signature
        timestamp=headers["X-Slack-Request-Timestamp"],
        signature=headers["X-Slack-Signature"],
    )


def test_verify_signature_false_without_secret(settings: Settings) -> None:
    settings.slack_signing_secret = ""
    assert not slack.verify_signature(settings, body="x", timestamp="0", signature="v0=bad")


# --- endpoint -------------------------------------------------------------------


@pytest.fixture
def client(settings: Settings) -> TestClient:
    settings.slack_signing_secret = SECRET
    return TestClient(server.app)


def test_interactivity_resolves_approval(client: TestClient) -> None:
    body = _interaction_body("c-gate", "approve")
    response = client.post("/slack/interactivity", content=body, headers=_signed_headers(body))
    assert response.status_code == 200
    assert response.json() == {"case_id": "c-gate", "action": "approve", "status": "approved"}


def test_interactivity_override_status(client: TestClient) -> None:
    body = _interaction_body("c-gate", "override")
    response = client.post("/slack/interactivity", content=body, headers=_signed_headers(body))
    assert response.json()["status"] == "overridden"


def test_interactivity_rejects_bad_signature(client: TestClient) -> None:
    body = _interaction_body("c-gate", "approve")
    headers = {
        "X-Slack-Request-Timestamp": str(int(time.time())),
        "X-Slack-Signature": "v0=deadbeef",
        "Content-Type": "application/x-www-form-urlencoded",
    }
    response = client.post("/slack/interactivity", content=body, headers=headers)
    assert response.status_code == 401


def test_interactivity_503_without_secret(settings: Settings) -> None:
    settings.slack_signing_secret = ""
    local_client = TestClient(server.app)
    body = _interaction_body("c-gate", "approve")
    response = local_client.post(
        "/slack/interactivity", content=body, headers=_signed_headers(body)
    )
    assert response.status_code == 503

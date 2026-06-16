"""Slack interactivity helpers: verify inbound callbacks and parse the payload.

When a compliance officer clicks Approve / Override / Request-Info on the approval
message, Slack POSTs a signed, form-encoded interaction to the app's Request URL.
We verify the request signature (HMAC over the raw body, with replay protection) and
extract the (case_id, action) so the API can resolve the approval gate.

The block_id on the approval message is ``approval::{case_id}`` (see
nodes/approval_gate.py), which is how we recover the case from the callback.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING
from urllib.parse import parse_qs

if TYPE_CHECKING:
    from compliance_agent.config import Settings

_BLOCK_PREFIX = "approval::"


def verify_signature(settings: Settings, body: str, timestamp: str, signature: str) -> bool:
    """Return True if the request signature is valid (and not stale)."""
    if not settings.slack_signing_secret:
        return False
    from slack_sdk.signature import SignatureVerifier

    verifier = SignatureVerifier(settings.slack_signing_secret)
    return verifier.is_valid(body=body, timestamp=timestamp, signature=signature)


def parse_interaction(body: str) -> tuple[str, str]:
    """Parse a Slack interaction body into (case_id, action).

    Raises ValueError if the payload is missing fields or the block_id is not an
    approval block.
    """
    form = parse_qs(body)
    raw_payload = form.get("payload", [""])[0]
    if not raw_payload:
        raise ValueError("missing payload")
    payload = json.loads(raw_payload)

    actions = payload.get("actions") or []
    if not actions:
        raise ValueError("no actions in payload")
    action = actions[0]
    action_id = str(action.get("action_id", ""))
    block_id = str(action.get("block_id", ""))

    if not block_id.startswith(_BLOCK_PREFIX):
        raise ValueError(f"unexpected block_id: {block_id!r}")
    case_id = block_id[len(_BLOCK_PREFIX) :]
    if not case_id or not action_id:
        raise ValueError("missing case_id or action_id")
    return case_id, action_id

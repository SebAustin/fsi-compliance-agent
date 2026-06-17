"""FastAPI server: run reviews, resolve approvals, verify the audit log.

Endpoints
- POST /review              run the compliance graph on a case
- GET  /approvals          list cases awaiting human approval
- POST /approvals/{id}     resolve an approval (approve / override / request_info)
- POST /slack/interactivity resolve an approval from a signed Slack button click
- GET  /audit/verify       verify the hash-chained audit log integrity
- GET  /audit/case/{id}    per-case audit trail as a Markdown examiner report
"""

from __future__ import annotations

from typing import Any

import structlog
from fastapi import FastAPI, HTTPException, Request, Response
from pydantic import BaseModel, Field

from compliance_agent import slack
from compliance_agent.audit.log import AuditLog
from compliance_agent.audit.report import render_case_report
from compliance_agent.config import get_settings
from compliance_agent.graph import build_graph
from compliance_agent.nodes.approval_gate import pending_case_ids, resolve_approval
from compliance_agent.rulebook.indexer import load_rules

log = structlog.get_logger(__name__)

app = FastAPI(title="fsi-compliance-agent", version="0.1.0")
_graph = build_graph()


class ReviewRequest(BaseModel):
    case_id: str = Field(min_length=1)
    case_text: str = Field(min_length=1)


class ApprovalRequest(BaseModel):
    action: str = Field(description="approve | override | request_info")


def _serialize(state: dict[str, Any]) -> dict[str, Any]:
    determination = state.get("determination")
    return {
        "case_id": state.get("case_id"),
        "case_type": state.get("case_type"),
        "risk_tier": state.get("risk_tier"),
        "decision": determination.decision if determination else None,
        "confidence": determination.confidence if determination else None,
        "citations": [c.model_dump() for c in determination.citations] if determination else [],
        "abstained": state.get("abstained", False),
        "approval_required": state.get("approval_required", False),
        "approval_status": state.get("approval_status"),
        "final_decision": state.get("final_decision"),
    }


@app.post("/review")
async def review(request: ReviewRequest) -> dict[str, Any]:
    """Run the compliance graph on a single case."""
    result = await _graph.ainvoke({"case_id": request.case_id, "case_text": request.case_text})
    return _serialize(dict(result))


@app.get("/approvals")
async def list_approvals() -> dict[str, list[str]]:
    """List case ids currently awaiting an approval decision."""
    return {"pending": pending_case_ids()}


@app.post("/approvals/{case_id}")
async def resolve(case_id: str, request: ApprovalRequest) -> dict[str, str]:
    """Resolve a pending approval."""
    try:
        status = resolve_approval(case_id, request.action)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"case_id": case_id, "status": status}


@app.get("/audit/verify")
async def verify_audit() -> dict[str, bool]:
    """Verify the integrity of the hash-chained audit log."""
    audit = AuditLog(get_settings().audit_log_path)
    return {"valid": audit.verify()}


@app.get("/audit/case/{case_id}")
async def audit_case(case_id: str) -> Response:
    """Return the full per-case audit trail rendered as a Markdown examiner report."""
    audit = AuditLog(get_settings().audit_log_path)
    entries = audit.read_case(case_id)
    if not entries:
        raise HTTPException(status_code=404, detail=f"No audit trail for case {case_id}")
    rules_by_id = {r["rule_id"]: r for r in load_rules()}
    markdown = render_case_report(case_id, entries, rules_by_id, integrity_ok=audit.verify())
    return Response(content=markdown, media_type="text/markdown")


@app.post("/slack/interactivity")
async def slack_interactivity(request: Request) -> dict[str, str]:
    """Resolve an approval from a signed Slack button interaction.

    Slack POSTs a signed, form-encoded payload when a compliance officer clicks
    Approve / Override / Request-Info. We verify the signature over the raw body
    (with replay protection) before acting on it.
    """
    settings = get_settings()
    if not settings.slack_signing_secret:
        raise HTTPException(status_code=503, detail="Slack signing secret not configured")

    body = (await request.body()).decode()
    valid = slack.verify_signature(
        settings,
        body=body,
        timestamp=request.headers.get("X-Slack-Request-Timestamp", ""),
        signature=request.headers.get("X-Slack-Signature", ""),
    )
    if not valid:
        raise HTTPException(status_code=401, detail="Invalid Slack signature")

    try:
        case_id, action = slack.parse_interaction(body)
        status = resolve_approval(case_id, action)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    return {"case_id": case_id, "action": action, "status": status}


def main() -> None:
    """Console-script entrypoint."""
    import uvicorn

    uvicorn.run("compliance_agent.api.server:app", host="0.0.0.0", port=8000)  # noqa: S104


if __name__ == "__main__":
    main()

"""Eval for fsi-compliance-agent.

Headline metric: false-negative rate (missed flags). In compliance, the
cost-asymmetric error is the one that matters — a transaction that should have been
flagged but was auto-cleared is the regulatory finding, not a UX annoyance.

The Slack approval gate is mocked here (auto-approve) so the pipeline completes, but
we still record that approval WAS required for each high-risk flag.

Usage: uv run python -m evals.run_eval --limit 80
"""

from __future__ import annotations

import asyncio
import json
import subprocess
from pathlib import Path

import structlog
import typer

from compliance_agent import providers
from compliance_agent.graph import build_graph
from compliance_agent.nodes import approval_gate
from compliance_agent.nodes.exceptions import CitationContractError
from evals.judge import judge_determination

log = structlog.get_logger(__name__)
app = typer.Typer(add_completion=False)

FLAG_LABELS = frozenset({"flag", "needs_review"})
FN_RATE_GATE = 0.03
CITATION_GATE = 0.99


def _git_sha() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "--short", "HEAD"]).decode().strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return "nogit"


def _load(limit: int, cases_path: str) -> list[dict[str, str]]:
    rows = [json.loads(line) for line in Path(cases_path).read_text().splitlines() if line.strip()]
    return rows[:limit] if limit else rows


async def _auto_approve(_case_id: str, _event: object, _timeout: int) -> str:
    """Mock the Slack gate: auto-approve so the eval pipeline completes."""
    return "approved"


@app.command()
def main(
    limit: int = typer.Option(0, "--limit"),
    cases_path: str = typer.Option("evals/cases.jsonl", "--cases"),
) -> None:
    """Run the eval and gate CI on false-negative rate + citation coverage."""
    # Mock the human gate without auto-approving in production code paths.
    approval_gate._await_resolution = _auto_approve  # type: ignore[assignment]  # noqa: SLF001

    providers.reset_cost()
    graph = build_graph()
    cases = _load(limit, cases_path)

    false_negatives = 0
    correct = decided = cited = abstained_n = approvals_required = 0
    contract_failures = 0
    quality: list[float] = []

    for case in cases:
        try:
            state = asyncio.run(
                graph.ainvoke({"case_id": case["case_id"], "case_text": case["case_text"]})
            )
        except CitationContractError:
            # An uncited determination is a contract failure, not a silent pass.
            contract_failures += 1
            log.warning("eval.contract_failure", case_id=case["case_id"])
            continue

        if state.get("abstained", False):
            abstained_n += 1
            continue  # routed to a human — not an auto-decision

        determination = state.get("determination")
        if determination is None:
            continue

        decided += 1
        if determination.citations:
            cited += 1
        if state.get("approval_required"):
            approvals_required += 1

        predicted = state.get("final_decision", determination.decision)
        should_flag = case["label"] in FLAG_LABELS

        if predicted == "compliant" and should_flag:
            false_negatives += 1
        if (predicted in FLAG_LABELS) == should_flag:
            correct += 1

        quality.append(asyncio.run(judge_determination(case["case_text"], determination.rationale)))

    n = len(cases)
    summary = {
        "git_sha": _git_sha(),
        "n": n,
        "false_negative_rate": round(false_negatives / n, 3) if n else None,
        "determination_accuracy": round(correct / decided, 3) if decided else None,
        "citation_coverage": round(cited / decided, 3) if decided else None,
        "abstention_rate": round(abstained_n / n, 3) if n else None,
        "approvals_required": approvals_required,
        "contract_failures": contract_failures,
        "resolution_quality": round(sum(quality) / len(quality), 3) if quality else None,
        "est_cost_usd_total": round(providers.total_cost_usd(), 4),
        "est_cost_usd_per_case": round(providers.total_cost_usd() / n, 4) if n else None,
    }

    out = Path("evals/runs") / _git_sha()
    out.mkdir(parents=True, exist_ok=True)
    (out / "summary.json").write_text(json.dumps(summary, indent=2))
    typer.echo(json.dumps(summary, indent=2))

    fn_rate = summary["false_negative_rate"] or 0.0
    coverage = summary["citation_coverage"] or 0.0
    ok = fn_rate <= FN_RATE_GATE and coverage >= CITATION_GATE
    raise typer.Exit(0 if ok else 1)


if __name__ == "__main__":
    app()

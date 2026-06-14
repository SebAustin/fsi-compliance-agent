"""Review a single case from the command line.

Usage: uv run python -m scripts.review --case "Wire transfer of $9,500 ..."
"""

from __future__ import annotations

import asyncio
import json

import typer

from compliance_agent.graph import build_graph

app = typer.Typer(add_completion=False)


@app.command()
def main(
    case: str = typer.Option(..., "--case", help="Free-text case / transaction description"),
    case_id: str = typer.Option("cli-001", "--case-id"),
) -> None:
    """Run the compliance graph on one case and print the determination."""
    graph = build_graph()
    state = asyncio.run(graph.ainvoke({"case_id": case_id, "case_text": case}))
    determination = state.get("determination")
    out = {
        "case_id": case_id,
        "case_type": state.get("case_type"),
        "risk_tier": state.get("risk_tier"),
        "decision": determination.decision if determination else None,
        "confidence": determination.confidence if determination else None,
        "citations": [c.model_dump() for c in determination.citations] if determination else [],
        "abstained": state.get("abstained"),
        "approval_required": state.get("approval_required"),
        "approval_status": state.get("approval_status"),
        "final_decision": state.get("final_decision"),
    }
    typer.echo(json.dumps(out, indent=2))


if __name__ == "__main__":
    app()

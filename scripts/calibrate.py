"""Fit the abstention threshold via split conformal prediction.

Runs triage -> retrieval -> determination on the labeled cases, collects the
nonconformity scores (1 - confidence) on the determinations that were CORRECT, and
sets the threshold tau at the conformal quantile for alpha (default 0.05). At
serving time the agent abstains when 1 - confidence > tau.

alpha=0.05 is deliberately stricter than a typical RAG system (0.10): compliance
tolerates fewer wrong auto-decisions, so we hand more uncertainty to a human.

Usage: uv run python -m scripts.calibrate
"""

from __future__ import annotations

import asyncio
import json
import math
from pathlib import Path

import numpy as np
import structlog
import typer

from compliance_agent.config import CALIBRATION_PATH, get_settings
from compliance_agent.nodes.determination import determination_node
from compliance_agent.nodes.rule_retrieval import rule_retrieval_node
from compliance_agent.nodes.triage import triage_node
from compliance_agent.state import CaseState

log = structlog.get_logger(__name__)
app = typer.Typer(add_completion=False)

CASES_PATH = Path("evals/cases.jsonl")
FLAG_LABELS = frozenset({"flag", "needs_review"})


def _load_cases() -> list[dict[str, str]]:
    return [json.loads(line) for line in CASES_PATH.read_text().splitlines() if line.strip()]


def _is_correct(predicted: str, label: str) -> bool:
    """Correct at the flag/clear level — the decision boundary that matters."""
    return (predicted in FLAG_LABELS) == (label in FLAG_LABELS)


async def _score_case(case: dict[str, str]) -> tuple[bool, float]:
    state: CaseState = {"case_id": case["case_id"], "case_text": case["case_text"]}
    state = await triage_node(state)
    state = await rule_retrieval_node(state)
    state = await determination_node(state)
    determination = state["determination"]
    correct = _is_correct(determination.decision, case["label"])
    return correct, 1.0 - determination.confidence


def conformal_quantile(scores: list[float], alpha: float) -> float:
    """Split-conformal (1-alpha) quantile with finite-sample correction."""
    n = len(scores)
    if n == 0:
        return 1.0
    rank = math.ceil((n + 1) * (1.0 - alpha))
    level = min(1.0, rank / n)
    return float(np.quantile(np.array(scores), level, method="higher"))


@app.command()
def main() -> None:
    """Calibrate and persist the abstention threshold."""
    settings = get_settings()
    cases = _load_cases()
    nonconformity: list[float] = []
    for case in cases:
        correct, score = asyncio.run(_score_case(case))
        if correct:
            nonconformity.append(score)

    tau = conformal_quantile(nonconformity, settings.abstention_alpha)
    CALIBRATION_PATH.write_text(
        json.dumps(
            {
                "abstention_threshold": tau,
                "alpha": settings.abstention_alpha,
                "n_calibration": len(nonconformity),
            },
            indent=2,
        )
    )
    typer.echo(
        f"Calibrated tau={tau:.4f} at alpha={settings.abstention_alpha} "
        f"on {len(nonconformity)} correct determinations -> {CALIBRATION_PATH}"
    )


if __name__ == "__main__":
    app()

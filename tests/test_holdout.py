"""Guard the held-out test set: well-formed and disjoint from the calibration set.

The held-out set only has integrity as an out-of-distribution measure if its cases
never overlap the calibration set the rules were tuned against.
"""

from __future__ import annotations

import json
from pathlib import Path

_LABELS = {"compliant", "flag", "needs_review"}


def _load(path: str) -> list[dict[str, str]]:
    return [json.loads(line) for line in Path(path).read_text().splitlines() if line.strip()]


def test_holdout_is_well_formed() -> None:
    rows = _load("evals/holdout.jsonl")
    assert len(rows) >= 25
    for row in rows:
        assert {"case_id", "case_text", "label"} <= set(row)
        assert row["label"] in _LABELS


def test_holdout_disjoint_from_calibration() -> None:
    calib_ids = {r["case_id"] for r in _load("evals/cases.jsonl")}
    holdout_ids = {r["case_id"] for r in _load("evals/holdout.jsonl")}
    assert calib_ids.isdisjoint(holdout_ids)

    calib_text = {r["case_text"] for r in _load("evals/cases.jsonl")}
    holdout_text = {r["case_text"] for r in _load("evals/holdout.jsonl")}
    assert calib_text.isdisjoint(holdout_text)  # no copied case text

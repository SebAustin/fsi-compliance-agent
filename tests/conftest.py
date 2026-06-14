"""Shared fixtures. Every network boundary is mocked so the suite runs offline."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from compliance_agent import config
from compliance_agent.state import CitedRule, Determination

if TYPE_CHECKING:
    from collections.abc import Iterator


@pytest.fixture
def audit_path(tmp_path: Path) -> Path:
    """An isolated audit-log path under tmp."""
    return tmp_path / "audit" / "log.jsonl"


@pytest.fixture
def settings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[config.Settings]:
    """The cached Settings instance, pointed at tmp dirs.

    Nodes import ``get_settings`` by name and call it, so the cached instance is
    shared process-wide. We mutate that instance (rather than swap the function) so
    every node and the tests see the same configuration.
    """
    monkeypatch.setattr(config, "CALIBRATION_PATH", tmp_path / ".calibration.json")
    config.get_settings.cache_clear()
    instance = config.get_settings()
    instance.audit_log_path = tmp_path / "audit" / "log.jsonl"
    instance.anthropic_api_key = ""
    instance.voyage_api_key = ""
    instance.slack_bot_token = ""
    yield instance
    config.get_settings.cache_clear()


def make_determination(
    decision: str = "flag",
    confidence: float = 0.9,
    *,
    cited: bool = True,
) -> Determination:
    """Build a Determination for tests."""
    citations = (
        [CitedRule(rule_id="AML-002", cited_text="structuring", start_char=0, end_char=11)]
        if cited
        else []
    )
    return Determination(
        decision=decision,  # type: ignore[arg-type]
        rationale="test rationale",
        confidence=confidence,
        citations=citations,
    )

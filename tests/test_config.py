"""Configuration and calibration-threshold loading."""

from __future__ import annotations

import json

from compliance_agent import config


def test_default_threshold_when_no_calibration(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(config, "CALIBRATION_PATH", tmp_path / "missing.json")
    settings = config.Settings(abstention_threshold=0.6)
    assert settings.calibrated_threshold() == 0.6


def test_calibrated_threshold_overrides_default(monkeypatch, tmp_path) -> None:
    path = tmp_path / ".calibration.json"
    path.write_text(json.dumps({"abstention_threshold": 0.42}))
    monkeypatch.setattr(config, "CALIBRATION_PATH", path)
    settings = config.Settings(abstention_threshold=0.6)
    assert settings.calibrated_threshold() == 0.42


def test_alpha_default_is_strict() -> None:
    assert config.Settings().abstention_alpha == 0.05

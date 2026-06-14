"""Configuration via pydantic-settings. Thresholds come from here or calibration —
never hardcoded at the call site.
"""

from __future__ import annotations

import functools
import json
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

CALIBRATION_PATH = Path(".calibration.json")


class Settings(BaseSettings):
    """Runtime configuration. Loaded from environment / .env."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # LLM + embeddings
    anthropic_api_key: str = ""
    voyage_api_key: str = ""

    # Vector store
    qdrant_url: str = "http://localhost:6333"
    qdrant_api_key: str = ""
    qdrant_collection: str = "compliance_rulebook"

    # Abstention / conformal calibration
    abstention_alpha: float = 0.05
    abstention_threshold: float = 0.60  # overwritten by calibration

    # Slack HITL
    slack_bot_token: str = ""
    slack_approval_channel: str = "#compliance-approvals"
    approval_timeout_s: int = 3600

    # Models (pinned Jun 2026)
    haiku_model: str = "claude-haiku-4-5-20250929"
    sonnet_model: str = "claude-sonnet-4-6"
    judge_model: str = "claude-opus-4-7"

    # Embeddings
    embed_model: str = "voyage-3-large"
    embed_dim: int = 256

    # Audit
    audit_log_path: Path = Path("audit/audit_log.jsonl")

    def calibrated_threshold(self) -> float:
        """Return the calibrated abstention threshold if present, else the default.

        Calibration writes the fitted nonconformity quantile to ``.calibration.json``.
        We never silently fall back without surfacing it to the caller via logs.
        """
        if CALIBRATION_PATH.exists():
            data = json.loads(CALIBRATION_PATH.read_text())
            value = data.get("abstention_threshold")
            if isinstance(value, int | float):
                return float(value)
        return self.abstention_threshold


@functools.lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Cached settings accessor."""
    return Settings()

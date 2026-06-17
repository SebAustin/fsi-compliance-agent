"""Compliance case state and the pydantic contracts that ride on it.

These models ARE the compliance contract. A `Determination` with no `citations`
for a compliant/flag decision is rejected upstream in the determination node —
in compliance you cannot clear or flag a transaction on an uncited basis.
"""

from __future__ import annotations

from typing import Literal, NotRequired, TypedDict

from pydantic import BaseModel, ConfigDict, Field

RiskTier = Literal["low", "medium", "high"]
Decision = Literal["compliant", "flag", "needs_review"]


class CitedRule(BaseModel):
    """A single rule clause the determination relied on, with char offsets.

    Offsets are into the cited document (the retrieved rule clause) and come from
    the Citations API so the citation is verifiable against the source text.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    rule_id: str
    cited_text: str
    start_char: int = Field(ge=0)
    end_char: int = Field(ge=0)


class Determination(BaseModel):
    """The compliance determination for a case."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    decision: Decision
    rationale: str
    confidence: float = Field(ge=0.0, le=1.0)
    citations: list[CitedRule] = Field(default_factory=list)


class RetrievedRule(BaseModel):
    """A rulebook clause surfaced by retrieval, with its similarity score."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    rule_id: str
    title: str
    category: str
    clause: str
    score: float


class CaseState(TypedDict):
    """LangGraph state threaded through the compliance review graph."""

    case_id: str
    case_text: str
    case_type: NotRequired[str]
    risk_tier: NotRequired[RiskTier]
    retrieved_rules: NotRequired[list[dict[str, object]]]
    determination: NotRequired[Determination]
    abstained: NotRequired[bool]
    escalation_reason: NotRequired[str]  # why an auto-decision was escalated to a human
    approval_required: NotRequired[bool]
    approval_status: NotRequired[str]  # pending / approved / overridden
    final_decision: NotRequired[Decision]

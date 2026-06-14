"""Domain exceptions for the compliance graph."""

from __future__ import annotations


class CitationContractError(ValueError):
    """Raised when a compliant/flag determination carries zero citations.

    In compliance you cannot clear or flag a transaction on an uncited basis;
    an uncited determination is invalid, not merely low quality.
    """


class ApprovalGateError(RuntimeError):
    """Raised when the approval gate cannot be reached and no safe default exists."""

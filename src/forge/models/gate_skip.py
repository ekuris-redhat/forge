"""Model representing PR Gate Skip Settings."""

from dataclasses import dataclass
from datetime import datetime


@dataclass
class PRGateSkipSettings:
    """Settings to persist and retrieve gate-skipping configurations for pull requests."""

    repo: str
    pr_number: int
    skip_gate: bool
    updated_by: str
    updated_at: datetime

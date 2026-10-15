"""What every step receives besides the client: settings and the Discovery to fill."""

from __future__ import annotations

from dataclasses import dataclass

from baqueano import model
from baqueano.model import Discovery


@dataclass
class Settings:
    sample: int = 200          # instances sampled per class
    max_classes: int = 30      # classes to profile
    graph: str | None = None   # --graph scope


@dataclass
class Context:
    discovery: Discovery
    settings: Settings


def step_status(outcome_status: str) -> str:
    """Map a client outcome status to the step status reported for a failure."""
    if outcome_status == "timeout":
        return model.TIMEOUT
    if outcome_status == "budget_exhausted":
        return model.SKIPPED
    return model.ERROR

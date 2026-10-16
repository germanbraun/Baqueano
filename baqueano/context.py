"""What every step receives besides the client: settings and the Discovery to fill."""

from __future__ import annotations

from dataclasses import dataclass, field

from baqueano import model
from baqueano.model import Discovery
from baqueano.profiling import Sample


@dataclass
class Settings:
    sample: int = 200          # instances sampled per class
    max_classes: int = 30      # classes to profile
    graph: str | None = None   # --graph scope
    class_property: str = "http://www.w3.org/1999/02/22-rdf-syntax-ns#type"   # what links instances to classes
    classes: list[str] = field(default_factory=list)   # --class: profiled first, in this order
    seed: int = 1              # random-offset sampling is reproducible for a given seed


@dataclass
class Context:
    discovery: Discovery
    settings: Settings
    # Raw samples by class IRI, filled by the profile step for the validate
    # step. In memory only: not part of the Discovery.
    samples: dict[str, Sample] = field(default_factory=dict)


# From best to worst, to combine the statuses of a step's sub-parts.
SEVERITY = [model.OK, model.UNSUPPORTED, model.SAMPLED, model.TIMEOUT, model.SKIPPED, model.ERROR]


def worst(*statuses: str) -> str:
    return max(statuses, key=SEVERITY.index)


def step_status(outcome_status: str) -> str:
    """Map a client outcome status to the step status reported for a failure."""
    if outcome_status == "timeout":
        return model.TIMEOUT
    if outcome_status == "budget_exhausted":
        return model.SKIPPED
    return model.ERROR

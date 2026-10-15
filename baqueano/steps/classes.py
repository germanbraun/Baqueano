"""Step 5: classes in use (?s a ?class), most populated first.

Fallback chain, stopping at the first that works:
    1. exact counts (GROUP BY)                      -> count_exact=True,  ok
    2. counts declared in VoID class partitions     -> count_exact=False, sampled
    3. DISTINCT sample of classes, no counts        -> count=None,        sampled
Labels and comments are filled later by the vocabulary step.
"""

from __future__ import annotations

import logging

from baqueano import model, scope
from baqueano.context import Context, step_status
from baqueano.model import ClassInfo, StepResult
from baqueano.rows import int_value, iri

logger = logging.getLogger(__name__)

NAME = "classes"
SAMPLE_STEP = "classes:sample"
CLASSES_LIMIT = 500


def counts_query(graph: str | None) -> str:
    return (f"SELECT ?class (COUNT(?s) AS ?n) WHERE {{ {scope.where('?s a ?class', graph)} }}\n"
            f"GROUP BY ?class ORDER BY DESC(?n) LIMIT {CLASSES_LIMIT}")


def sample_query(graph: str | None) -> str:
    return f"SELECT DISTINCT ?class WHERE {{ {scope.where('?s a ?class', graph)} }} LIMIT {CLASSES_LIMIT}"


def classes_from_counts(rows: list[dict]) -> list[ClassInfo]:
    """Rows of counts_query -> ClassInfo, most populated first (pure)."""
    classes = [ClassInfo(iri=c, count=int_value(r, "n"), count_exact=True)
               for r in rows if (c := iri(r, "class"))]
    return sorted(classes, key=lambda c: -(c.count or 0))


def classes_from_void(partitions: dict[str, int | None]) -> list[ClassInfo]:
    """VoID class partitions -> ClassInfo, declared counts, not exact (pure)."""
    classes = [ClassInfo(iri=c, count=n, count_exact=False) for c, n in partitions.items()]
    return sorted(classes, key=lambda c: -(c.count or 0))


def classes_from_sample(rows: list[dict]) -> list[ClassInfo]:
    """Rows of sample_query -> ClassInfo without counts, in engine order (pure)."""
    return [ClassInfo(iri=c, count=None, count_exact=False) for r in rows if (c := iri(r, "class"))]


def limit_note(n_rows: int) -> str:
    return f" (limit {CLASSES_LIMIT} reached, there may be more)" if n_rows >= CLASSES_LIMIT else ""


def run(client, ctx: Context) -> StepResult:
    discovery = ctx.discovery
    graph = ctx.settings.graph

    counted = client.query(NAME, counts_query(graph))
    if counted.status == "ok":
        discovery.classes = classes_from_counts(counted.rows)
        return StepResult(NAME, model.OK,
                          f"{len(discovery.classes)} classes with exact counts{limit_note(len(counted.rows))}")
    reason = f"count query {counted.status}"
    logger.debug("%s (%s); trying fallbacks", reason, counted.error)

    partitions = (discovery.void or {}).get("class_partitions")
    if partitions:
        discovery.classes = classes_from_void(partitions)
        return StepResult(NAME, model.SAMPLED,
                          f"{reason}; {len(discovery.classes)} classes with counts declared in VoID")

    sampled = client.query(SAMPLE_STEP, sample_query(graph))
    if sampled.status == "ok":
        discovery.classes = classes_from_sample(sampled.rows)
        return StepResult(NAME, model.SAMPLED,
                          f"{reason}; {len(discovery.classes)} classes found without counts"
                          f"{limit_note(len(sampled.rows))}")
    return StepResult(NAME, step_status(sampled.status), f"{reason}; class sample also failed: {sampled.error}")

"""Step 5: classes in use (?s a ?class, or ?s <P> ?class with --class-property),
most populated first.

Fallback chain, stopping at the first that works:
    1. exact counts (GROUP BY)                      -> count_exact=True,  ok
    2. counts declared in VoID class partitions     -> count_exact=False, sampled
    3. DISTINCT sample of classes, no counts        -> count=None,        sampled
VoID class partitions describe rdf:type classes, so step 2 is only used when
the class property is rdf:type. Classes requested with --class that the
listing did not return are appended without a count.
Labels and comments are filled later by the vocabulary step.
"""

from __future__ import annotations

import logging

from baqueano import model, scope
from baqueano.context import Context, step_status
from baqueano.model import ClassInfo, StepResult
from baqueano.rows import int_value, iri
from baqueano.vocabularies import RDF_TYPE

logger = logging.getLogger(__name__)

NAME = "classes"
SAMPLE_STEP = "classes:sample"
CLASSES_LIMIT = 500


def counts_query(graph: str | None, class_property: str = RDF_TYPE) -> str:
    pattern = scope.is_a("?s", "?class", class_property)
    return (f"SELECT ?class (COUNT(?s) AS ?n) WHERE {{ {scope.where(pattern, graph)} }}\n"
            f"GROUP BY ?class ORDER BY DESC(?n) LIMIT {CLASSES_LIMIT}")


def sample_query(graph: str | None, class_property: str = RDF_TYPE) -> str:
    pattern = scope.is_a("?s", "?class", class_property)
    return f"SELECT DISTINCT ?class WHERE {{ {scope.where(pattern, graph)} }} LIMIT {CLASSES_LIMIT}"


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


def find_classes(client, ctx: Context) -> StepResult:
    discovery = ctx.discovery
    graph, class_property = ctx.settings.graph, ctx.settings.class_property

    counted = client.query(NAME, counts_query(graph, class_property))
    if counted.status == "ok":
        discovery.classes = classes_from_counts(counted.rows)
        return StepResult(NAME, model.OK,
                          f"{len(discovery.classes)} classes with exact counts{limit_note(len(counted.rows))}")
    reason = f"count query {counted.status}"
    logger.debug("%s (%s); trying fallbacks", reason, counted.error)

    partitions = (discovery.void or {}).get("class_partitions")
    if partitions and class_property == RDF_TYPE:
        discovery.classes = classes_from_void(partitions)
        return StepResult(NAME, model.SAMPLED,
                          f"{reason}; {len(discovery.classes)} classes with counts declared in VoID")

    sampled = client.query(SAMPLE_STEP, sample_query(graph, class_property))
    if sampled.status == "ok":
        discovery.classes = classes_from_sample(sampled.rows)
        return StepResult(NAME, model.SAMPLED,
                          f"{reason}; {len(discovery.classes)} classes found without counts"
                          f"{limit_note(len(sampled.rows))}")
    return StepResult(NAME, step_status(sampled.status), f"{reason}; class sample also failed: {sampled.error}")


def run(client, ctx: Context) -> StepResult:
    result = find_classes(client, ctx)
    known = {c.iri for c in ctx.discovery.classes}
    missing = [c for c in ctx.settings.classes if c not in known]
    if missing:
        logger.debug("requested classes not in the listing, added without count: %s", missing)
        ctx.discovery.classes += [ClassInfo(iri=c, count=None, count_exact=False) for c in missing]
        result.message = f"{result.message}; {len(missing)} requested class(es) added without count"
    return result

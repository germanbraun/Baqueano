"""Step 2: VoID description, if the endpoint publishes one.

Declared figures (void:triples, class partitions with void:entities,
void:vocabulary) are kept in discovery.void. Later steps use them only as a
fallback when their exact query fails, and always mark them as not exact.

discovery.void, when VoID is found:
    {
      "datasets":        {dataset: {predicate: [values]}},
      "triples":         largest void:triples declared, or None,
      "class_partitions": {class IRI: void:entities or None},
      "vocabularies":    [void:vocabulary values],
    }
"""

from __future__ import annotations

import logging

from baqueano import model, scope
from baqueano.context import Context, step_status
from baqueano.model import StepResult
from baqueano.rows import int_value, iri, node_id, value

logger = logging.getLogger(__name__)

NAME = "void"
PARTITIONS_STEP = "void:partitions"
VOID = "http://rdfs.org/ns/void#"
DATASETS_LIMIT = 500
PARTITIONS_LIMIT = 500


def datasets_query(graph: str | None) -> str:
    pattern = "?ds a void:Dataset ; ?p ?o"
    return (f"PREFIX void: <{VOID}>\n"
            f"SELECT ?ds ?p ?o WHERE {{ {scope.where(pattern, graph)} }} LIMIT {DATASETS_LIMIT}")


def partitions_query(graph: str | None) -> str:
    pattern = ("?ds void:classPartition ?cp . ?cp void:class ?class . "
               "OPTIONAL { ?cp void:entities ?entities }")
    return (f"PREFIX void: <{VOID}>\n"
            f"SELECT ?class ?entities WHERE {{ {scope.where(pattern, graph)} }} LIMIT {PARTITIONS_LIMIT}")


def summarize(dataset_rows: list[dict], partition_rows: list[dict]) -> dict:
    """Build discovery.void from the two queries' rows (pure)."""
    datasets: dict[str, dict[str, list[str]]] = {}
    triples: list[int] = []
    vocabularies: list[str] = []
    for row in dataset_rows:
        ds, p, o = node_id(row, "ds"), value(row, "p"), value(row, "o")
        if ds is None or p is None or o is None:
            continue
        datasets.setdefault(ds, {}).setdefault(p, []).append(o)
        if p == VOID + "triples":
            n = int_value(row, "o")
            if n is not None:
                triples.append(n)
        elif p == VOID + "vocabulary" and o not in vocabularies:
            vocabularies.append(o)

    # A class may appear in several (sub)datasets: keep the largest count.
    partitions: dict[str, int | None] = {}
    for row in partition_rows:
        cls = iri(row, "class")
        if cls is None:
            continue
        n = int_value(row, "entities")
        old = partitions.get(cls)
        partitions[cls] = n if old is None else max(old, n or 0)

    return {
        "datasets": datasets,
        "triples": max(triples) if triples else None,   # the top-level dataset is the largest
        "class_partitions": partitions,
        "vocabularies": vocabularies,
    }


def run(client, ctx: Context) -> StepResult:
    graph = ctx.settings.graph
    datasets = client.query(NAME, datasets_query(graph))
    if datasets.status != "ok":
        return StepResult(NAME, step_status(datasets.status), f"VoID query failed: {datasets.error}")
    if not datasets.rows:
        return StepResult(NAME, model.OK, "no VoID description published")

    partitions = client.query(PARTITIONS_STEP, partitions_query(graph))
    partition_rows = partitions.rows if partitions.status == "ok" else []
    void = summarize(datasets.rows, partition_rows or [])
    ctx.discovery.void = void

    message = (f"{len(void['datasets'])} dataset(s), "
               f"{len(void['class_partitions'])} class partition(s), "
               f"triples declared: {void['triples'] if void['triples'] is not None else 'no'}")
    if partitions.status != "ok":
        logger.debug("VoID class partitions failed: %s", partitions.error)
        return StepResult(NAME, step_status(partitions.status),
                          f"{message}; class partitions query failed: {partitions.error}")
    return StepResult(NAME, model.OK, message)

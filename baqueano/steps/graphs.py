"""Step 4: named graphs and total size.

- Named graphs: listed up to GRAPHS_LIMIT. With --graph there is nothing to
  list: the scope is that one graph.
- Size: exact COUNT(*). If it fails, fall back to void:triples (marked not
  exact, status sampled); otherwise the size is unknown.
The step status is the worst of the two parts.
"""

from __future__ import annotations

import logging

from baqueano import model, scope
from baqueano.context import Context, step_status, worst
from baqueano.model import Discovery, StepResult
from baqueano.rows import int_value, iri

logger = logging.getLogger(__name__)

NAME = "graphs"
COUNT_STEP = "graphs:count"
GRAPHS_LIMIT = 100


def graphs_query() -> str:
    return f"SELECT DISTINCT ?g WHERE {{ GRAPH ?g {{ ?s ?p ?o }} }} LIMIT {GRAPHS_LIMIT}"


def count_query(graph: str | None) -> str:
    return f"SELECT (COUNT(*) AS ?n) WHERE {{ {scope.where('?s ?p ?o', graph)} }}"


def list_graphs(client, discovery: Discovery, graph: str | None) -> tuple[str, str]:
    """Fill discovery.graphs. Returns (status, message)."""
    if graph is not None:
        discovery.graphs = [graph]
        return model.OK, f"scoped to <{graph}>"
    listed = client.query(NAME, graphs_query())
    if listed.status == "http_error" and listed.http_status == 400:
        # e.g. Blazegraph in triples mode (Wikidata) rejects GRAPH patterns outright.
        return model.UNSUPPORTED, "named graphs not supported by this endpoint (HTTP 400 on GRAPH ?g)"
    if listed.status != "ok":
        return step_status(listed.status), f"graph listing failed: {listed.error}"
    discovery.graphs = [g for g in (iri(r, "g") for r in listed.rows) if g]
    more = " (limit reached, there may be more)" if len(listed.rows) >= GRAPHS_LIMIT else ""
    return model.OK, f"{len(discovery.graphs)} named graph(s){more}"


def count_triples(client, discovery: Discovery, graph: str | None) -> tuple[str, str]:
    """Fill discovery.triple_count. Returns (status, message)."""
    counted = client.query(COUNT_STEP, count_query(graph))
    n = int_value(counted.rows[0], "n") if counted.status == "ok" and counted.rows else None
    if n is not None:
        discovery.triple_count, discovery.triple_count_exact = n, True
        return model.OK, f"{n} triples"

    reason = counted.error if counted.status != "ok" else "no count in the answer"
    declared = (discovery.void or {}).get("triples")
    if declared is not None:
        logger.debug("triple count failed (%s); using void:triples = %s", reason, declared)
        discovery.triple_count, discovery.triple_count_exact = declared, False
        return model.SAMPLED, f"count failed ({reason}); {declared} triples declared in VoID"
    failed = step_status(counted.status) if counted.status != "ok" else model.ERROR
    return failed, f"triple count unknown ({reason})"


def run(client, ctx: Context) -> StepResult:
    graph = ctx.settings.graph
    graphs_status, graphs_message = list_graphs(client, ctx.discovery, graph)
    count_status, count_message = count_triples(client, ctx.discovery, graph)
    return StepResult(NAME, worst(graphs_status, count_status), f"{graphs_message}; {count_message}")

"""Step 3: SHACL shapes already published in the endpoint.

Lists sh:NodeShapes and their sh:targetClass, then copies the shapes with a
CONSTRUCT two levels deep (the shape's triples, and the triples of its
property shapes / blank nodes) into discovery.found_shapes_ttl, which the CLI
writes as found-shapes.ttl. Deeper structures (e.g. long sh:in lists) may be
cut off at the second level.
"""

from __future__ import annotations

import logging

from baqueano import model, scope
from baqueano.context import Context, step_status
from baqueano.model import StepResult
from baqueano.rdf import parse_rdf
from baqueano.rows import iri, node_id

logger = logging.getLogger(__name__)

NAME = "shapes_found"
LIST_STEP = "shapes"
COPY_STEP = "shapes:construct"
SH = "http://www.w3.org/ns/shacl#"
SHAPES_LIMIT = 200
TRIPLES_LIMIT = 10000


def list_query(graph: str | None) -> str:
    pattern = "?shape a sh:NodeShape . OPTIONAL { ?shape sh:targetClass ?target }"
    return (f"PREFIX sh: <{SH}>\n"
            f"SELECT ?shape ?target WHERE {{ {scope.where(pattern, graph)} }} LIMIT {SHAPES_LIMIT}")


def copy_query(graph: str | None) -> str:
    pattern = (f"{{ SELECT DISTINCT ?shape WHERE {{ ?shape a sh:NodeShape }} LIMIT {SHAPES_LIMIT} }} "
               "?shape ?p ?o . "
               "OPTIONAL { ?o ?p2 ?o2 . FILTER(isBlank(?o) || ?p = sh:property) }")
    return (f"PREFIX sh: <{SH}>\n"
            f"CONSTRUCT {{ ?shape ?p ?o . ?o ?p2 ?o2 . }}\n"
            f"WHERE {{ {scope.where(pattern, graph)} }} LIMIT {TRIPLES_LIMIT}")


def shapes_from_rows(rows: list[dict]) -> list[dict]:
    """[{"shape", "target_class"}], one entry per (shape, target) pair (pure)."""
    found, seen = [], set()
    for row in rows:
        shape = node_id(row, "shape")
        target = iri(row, "target")
        if shape is None or (shape, target) in seen:
            continue
        seen.add((shape, target))
        found.append({"shape": shape, "target_class": target})
    return found


def run(client, ctx: Context) -> StepResult:
    graph = ctx.settings.graph
    listed = client.query(LIST_STEP, list_query(graph))
    if listed.status != "ok":
        return StepResult(NAME, step_status(listed.status), f"shapes query failed: {listed.error}")
    if not listed.rows:
        return StepResult(NAME, model.OK, "no SHACL shapes published")

    ctx.discovery.found_shapes = shapes_from_rows(listed.rows)
    n_shapes = len({s["shape"] for s in ctx.discovery.found_shapes})
    message = f"{n_shapes} shape(s)"

    copied = client.construct(COPY_STEP, copy_query(graph))
    if copied.status != "ok":
        return StepResult(NAME, step_status(copied.status), f"{message}; could not copy them: {copied.error}")
    rdf_graph = parse_rdf(copied.text or "", copied.content_type)
    if rdf_graph is None:
        return StepResult(NAME, model.ERROR,
                          f"{message}; CONSTRUCT answer is not parseable RDF ({copied.content_type})")

    rdf_graph.bind("sh", SH)
    ctx.discovery.found_shapes_ttl = rdf_graph.serialize(format="turtle")
    return StepResult(NAME, model.OK, f"{message}, {len(rdf_graph)} triples copied")

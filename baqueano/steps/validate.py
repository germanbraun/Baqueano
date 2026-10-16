"""Step 9: validate the profiled samples against the shapes (no queries).

Two sources of shapes:
- found:    published in the endpoint (discovery.found_shapes_ttl), for the
            profiled classes they target. This is real conformance checking.
- inferred: the draft shapes of shapes.ttl. They were built from these same
            samples, so they mostly hold; their violations are the outliers
            (e.g. the 3% of instances without a name).

Uses the raw samples kept in memory by the profile step (ctx.samples), so
it must run in the same `explore` as the profile.
"""

from __future__ import annotations

import logging

from baqueano import model
from baqueano.context import Context
from baqueano.generate.shapes import constraints_for, shape_names
from baqueano.model import Discovery, StepResult
from baqueano.profiling import RDF_TYPE
from baqueano.rdf import parse_rdf
from baqueano.validation import Constraint, PropertySpec, ShapeSpec, specs_from_graph, validate
from baqueano.vocabularies import shorten

logger = logging.getLogger(__name__)

NAME = "validate"


def inferred_specs(discovery: Discovery) -> list[ShapeSpec]:
    """The shapes of shapes.ttl as ShapeSpecs (same decisions, via constraints_for)."""
    names = shape_names(discovery.profiles)
    specs = []
    for prof in discovery.profiles:
        properties = []
        for pp in prof.properties:
            if pp.path == discovery.class_property:
                continue
            c = constraints_for(pp)
            if c is None:
                continue
            constraints = []
            if c.min_count:
                constraints.append(Constraint("minCount", 1, "1"))
            if c.max_count:
                constraints.append(Constraint("maxCount", 1, "1"))
            if c.datatype:
                constraints.append(Constraint("datatype", c.datatype, shorten(c.datatype)))
            if c.sh_class:
                constraints.append(Constraint("class", c.sh_class, shorten(c.sh_class)))
            if c.node_kind is not None:
                kind = str(c.node_kind).rsplit("#", 1)[-1]
                constraints.append(Constraint("nodeKind", kind, f"sh:{kind}"))
            if c.languages:
                constraints.append(Constraint("languageIn", c.languages, "(" + " ".join(c.languages) + ")"))
            properties.append(PropertySpec(pp.path, constraints))
        specs.append(ShapeSpec(shape=names[prof.class_iri], source="inferred", target_class=prof.class_iri,
                               severity="Info", properties=properties))
    return specs


def found_specs(discovery: Discovery) -> tuple[list[ShapeSpec], list[dict]]:
    if not discovery.found_shapes_ttl:
        return [], []
    if discovery.class_property != RDF_TYPE:
        # sh:targetClass selects rdf:type instances; our samples follow another property.
        return [], [{"shape": None, "path": None, "component": "targetClass",
                     "reason": f"published shapes target rdf:type classes, but classes were discovered "
                               f"with <{discovery.class_property}>"}]
    graph = parse_rdf(discovery.found_shapes_ttl, "text/turtle")
    if graph is None:
        return [], [{"shape": None, "path": None, "component": "all", "reason": "found-shapes.ttl did not parse"}]
    return specs_from_graph(graph)


def run(client, ctx: Context) -> StepResult:
    discovery = ctx.discovery
    if not ctx.samples:
        return StepResult(NAME, model.OK, "nothing to validate (no class was profiled)")

    found, not_checked = found_specs(discovery)
    untargeted = sorted({s.target_class for s in found if s.target_class not in ctx.samples})
    if untargeted:
        logger.debug("published shapes target classes that were not profiled: %s", untargeted)
    results = []
    for spec in [s for s in found if s.target_class in ctx.samples] + inferred_specs(discovery):
        if spec.target_class in ctx.samples:
            results += validate(spec, ctx.samples[spec.target_class])
    discovery.validation = results
    discovery.validation_not_checked = not_checked

    parts = []
    for source, label in (("found", "published shapes"), ("inferred", "inferred shapes")):
        rows = [r for r in results if r.source == source]
        if rows:
            failing = sum(1 for r in rows if r.violations)
            parts.append(f"{label}: {len(rows)} constraint(s) checked, {failing} with violations")
    if untargeted:
        parts.append(f"{len(untargeted)} published shape target(s) not profiled")
    if not_checked:
        parts.append(f"{len(not_checked)} constraint(s) not checked")
    return StepResult(NAME, model.OK, "; ".join(parts) or "no constraints to check")

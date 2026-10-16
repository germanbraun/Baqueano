"""Validating a class's sample against SHACL shapes: a SHACL Core subset (pure).

Shapes become ShapeSpecs (from published Turtle with `specs_from_graph`, or
built directly for the inferred shapes); `validate` checks one spec against
one Sample and returns a ConstraintResult per constraint.

Supported: targets by sh:targetClass; predicate paths; node-level and
property-level minCount, maxCount, datatype, class, nodeKind, languageIn,
in, hasValue, uniqueLang, pattern (+flags), minLength, maxLength,
min/maxInclusive, min/maxExclusive; sh:closed with sh:ignoredProperties.
Everything else (sh:or, sh:node, sh:sparql, complex paths, ...) is reported
as not checked, never silently ignored.

Limits of checking a sample, stated in the report:
- sh:class uses only the types fetched for checked objects (up to
  OBJECTS_PER_PROPERTY per property) and does no rdfs:subClassOf
  reasoning; undecidable values count as `unknown`, not as violations.
- values missing because a triples batch was truncated may show up as
  minCount violations.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

from rdflib import BNode, Graph, Literal, URIRef
from rdflib.namespace import RDF

from baqueano.model import ConstraintResult
from baqueano.profiling import Sample, literal_datatype
from baqueano.vocabularies import shorten

logger = logging.getLogger(__name__)

SH = "http://www.w3.org/ns/shacl#"
MAX_EXAMPLES = 3

OK, VIOLATION, UNKNOWN = "ok", "violation", "unknown"

# Components checked per value: a focus node fails if any value fails.
PER_VALUE = {"datatype", "class", "nodeKind", "languageIn", "in", "pattern", "minLength", "maxLength",
             "minInclusive", "maxInclusive", "minExclusive", "maxExclusive"}
# Components checked on the whole set of values of a focus node.
PER_SET = {"minCount", "maxCount", "hasValue", "uniqueLang"}
SUPPORTED = PER_VALUE | PER_SET

# SHACL predicates that are not constraints, or are read together with another one.
NOT_CONSTRAINTS = {"path", "name", "description", "severity", "message", "order", "group", "deactivated",
                   "defaultValue", "flags", "targetClass", "property", "closed", "ignoredProperties"}
TARGETS = {"targetClass", "targetNode", "targetSubjectsOf", "targetObjectsOf"}

NODE_KINDS = {
    "IRI": {"uri"}, "Literal": {"literal"}, "BlankNode": {"bnode"},
    "BlankNodeOrIRI": {"bnode", "uri"}, "BlankNodeOrLiteral": {"bnode", "literal"},
    "IRIOrLiteral": {"uri", "literal"},
}


@dataclass
class Constraint:
    component: str             # SHACL local name: "minCount", "class", ...
    parameter: object          # parsed value: int, IRI string, term dict, list of terms, (pattern, flags)
    text: str                  # parameter for the report


@dataclass
class PropertySpec:
    path: str | None           # None: node-level constraints (checked on the focus node itself)
    constraints: list[Constraint] = field(default_factory=list)


@dataclass
class ShapeSpec:
    shape: str
    source: str                # "found" | "inferred"
    target_class: str
    severity: str = "Violation"
    properties: list[PropertySpec] = field(default_factory=list)
    closed: bool = False
    ignored_properties: list[str] = field(default_factory=list)


# -- terms -----------------------------------------------------------------------

def to_term(node) -> dict:
    """rdflib node -> simplified term (same shape as client.simplify_term)."""
    if isinstance(node, URIRef):
        return {"type": "uri", "value": str(node)}
    if isinstance(node, BNode):
        return {"type": "bnode", "value": str(node)}
    term = {"type": "literal", "value": str(node)}
    if node.language:
        term["lang"] = node.language
    elif node.datatype:
        term["datatype"] = str(node.datatype)
    return term


def term_key(term: dict) -> tuple:
    """Identity for sh:in / sh:hasValue: plain literals are xsd:string, tags are case-insensitive."""
    if term["type"] != "literal":
        return (term["type"], term["value"])
    return ("literal", term["value"], literal_datatype(term), (term.get("lang") or "").lower())


def term_text(term: dict) -> str:
    if term["type"] == "uri":
        return shorten(term["value"])
    if term["type"] == "bnode":
        return f"_:{term['value']}"
    suffix = f"@{term['lang']}" if "lang" in term else (f"^^{shorten(term['datatype'])}" if "datatype" in term else "")
    return f'"{term["value"]}"{suffix}'


def to_python(term: dict):
    """Comparable Python value of a literal term, or None when it has none."""
    if term["type"] != "literal":
        return None
    value = Literal(term["value"], lang=term.get("lang"), datatype=term.get("datatype")).toPython()
    return None if isinstance(value, Literal) else value


# -- checks (one branch per component) -------------------------------------------

def lang_matches(lang: str, ranges: list[str]) -> bool:
    """SPARQL langMatches basic filtering, as sh:languageIn requires."""
    lang = lang.lower()
    for r in ranges:
        r = r.lower()
        if (r == "*" and lang) or lang == r or lang.startswith(r + "-"):
            return True
    return False


def check_value(c: Constraint, v: dict, object_types: dict[str, set[str]], checked: set[str]) -> str:
    """One value against one per-value constraint."""
    comp, param = c.component, c.parameter
    if comp == "datatype":
        return OK if v["type"] == "literal" and literal_datatype(v) == param else VIOLATION
    if comp == "class":
        if v["type"] == "literal":
            return VIOLATION
        if v["type"] == "bnode" or v["value"] not in checked:
            return UNKNOWN          # its types were not fetched
        return OK if param in object_types.get(v["value"], ()) else VIOLATION
    if comp == "nodeKind":
        return OK if v["type"] in NODE_KINDS.get(param, set()) else VIOLATION
    if comp == "languageIn":
        return OK if v["type"] == "literal" and lang_matches(v.get("lang", ""), param) else VIOLATION
    if comp == "in":
        return OK if term_key(v) in param else VIOLATION
    if comp in ("pattern", "minLength", "maxLength"):
        if v["type"] == "bnode":
            return VIOLATION
        if comp == "pattern":
            pattern, flags = param
            return OK if re.search(pattern, v["value"], flags) else VIOLATION
        n = len(v["value"])
        return OK if (n >= param if comp == "minLength" else n <= param) else VIOLATION
    # min/max Inclusive/Exclusive
    value, bound = to_python(v), param
    try:
        if comp == "minInclusive":
            return OK if value >= bound else VIOLATION
        if comp == "maxInclusive":
            return OK if value <= bound else VIOLATION
        if comp == "minExclusive":
            return OK if value > bound else VIOLATION
        return OK if value < bound else VIOLATION   # maxExclusive
    except TypeError:               # incomparable values are violations in SHACL
        return VIOLATION


def check(c: Constraint, values: list[dict], object_types: dict[str, set[str]], checked: set[str]) -> str:
    """The values of one focus node against one constraint."""
    comp, param = c.component, c.parameter
    if comp == "minCount":
        return OK if len(values) >= param else VIOLATION
    if comp == "maxCount":
        return OK if len(values) <= param else VIOLATION
    if comp == "hasValue":
        return OK if any(term_key(v) == term_key(param) for v in values) else VIOLATION
    if comp == "uniqueLang":
        if not param:
            return OK
        langs = [v["lang"].lower() for v in values if v.get("lang")]
        return OK if len(langs) == len(set(langs)) else VIOLATION
    results = [check_value(c, v, object_types, checked) for v in values]
    if VIOLATION in results:
        return VIOLATION
    return UNKNOWN if UNKNOWN in results else OK


# -- validation -------------------------------------------------------------------

def values_index(sample: Sample) -> dict[str, dict[str, list[dict]]]:
    """subject -> property -> object terms."""
    index: dict[str, dict[str, list[dict]]] = {s: {} for s in sample.subjects}
    for s, p, o in sample.triples:
        if s in index:
            index[s].setdefault(p, []).append(o)
    return index


def validate(spec: ShapeSpec, sample: Sample) -> list[ConstraintResult]:
    """Check every constraint of `spec` on every sampled instance."""
    index = values_index(sample)
    results = []

    def record(path, component, text, outcomes):
        failing = [s for s, outcome in outcomes if outcome == VIOLATION]
        results.append(ConstraintResult(
            shape=spec.shape, source=spec.source, target_class=spec.target_class, path=path,
            component=component, parameter=text, severity=spec.severity, checked=len(outcomes),
            violations=len(failing), unknown=sum(1 for _, o in outcomes if o == UNKNOWN),
            examples=failing[:MAX_EXAMPLES]))

    for prop in spec.properties:
        for c in prop.constraints:
            outcomes = []
            for s in sample.subjects:
                values = [{"type": "uri", "value": s}] if prop.path is None else index[s].get(prop.path, [])
                outcomes.append((s, check(c, values, sample.object_types, sample.checked)))
            record(prop.path, c.component, c.text, outcomes)

    if spec.closed:
        allowed = {p.path for p in spec.properties if p.path} | set(spec.ignored_properties)
        outcomes = [(s, OK if set(index[s]) <= allowed else VIOLATION) for s in sample.subjects]
        record(None, "closed", "ignored: " + (" ".join(shorten(p) for p in spec.ignored_properties) or "none"),
               outcomes)
    return results


# -- reading published shapes ------------------------------------------------------

def read_list(g: Graph, head) -> list | None:
    """Items of an rdf:List, or None when the list is broken (e.g. cut off by the copy)."""
    items, node, seen = [], head, set()
    while node != RDF.nil:
        first, rest = g.value(node, RDF.first), g.value(node, RDF.rest)
        if first is None or rest is None or node in seen:
            return None
        seen.add(node)
        items.append(first)
        node = rest
    return items


def node_id(node) -> str:
    return f"_:{node}" if isinstance(node, BNode) else str(node)


def parse_constraint(g: Graph, node, component: str, value) -> Constraint | str:
    """A Constraint, or the reason it cannot be checked."""
    if component not in SUPPORTED:
        return "not supported by Baqueano's validator"
    if component in ("minCount", "maxCount", "minLength", "maxLength"):
        n = value.toPython() if isinstance(value, Literal) else None
        return Constraint(component, n, str(n)) if isinstance(n, int) else "not an integer"
    if component in ("datatype", "class"):
        return Constraint(component, str(value), shorten(str(value))) if isinstance(value, URIRef) else "not an IRI"
    if component == "nodeKind":
        kind = str(value).removeprefix(SH)
        return Constraint(component, kind, f"sh:{kind}") if kind in NODE_KINDS else "unknown node kind"
    if component in ("languageIn", "in"):
        items = read_list(g, value)
        if items is None:
            return "list not fully available (copied only two levels deep)"
        if component == "languageIn":
            return Constraint(component, [str(i) for i in items], "(" + " ".join(str(i) for i in items) + ")")
        terms = [to_term(i) for i in items]
        return Constraint(component, {term_key(t) for t in terms}, "(" + " ".join(term_text(t) for t in terms) + ")")
    if component == "hasValue":
        term = to_term(value)
        return Constraint(component, term, term_text(term))
    if component == "uniqueLang":
        return Constraint(component, bool(value.toPython()), str(value))
    if component == "pattern":
        flags_node = g.value(node, URIRef(SH + "flags"))
        flags = 0
        for letter in str(flags_node or ""):
            flags |= {"i": re.IGNORECASE, "m": re.MULTILINE, "s": re.DOTALL, "x": re.VERBOSE}.get(letter, 0)
        try:
            re.compile(str(value), flags)
        except re.error as e:
            return f"pattern not valid in Python: {e}"
        return Constraint(component, (str(value), flags), str(value))
    # min/max Inclusive/Exclusive
    bound = to_python(to_term(value)) if isinstance(value, Literal) else None
    return Constraint(component, bound, term_text(to_term(value))) if bound is not None else "not a comparable literal"


def constraints_of(g: Graph, node, shape: str, path: str | None,
                   not_checked: list[dict]) -> list[Constraint]:
    constraints = []
    for p, value in sorted(g.predicate_objects(node)):
        if not str(p).startswith(SH):
            continue                  # annotations (rdfs:label, ...)
        component = str(p)[len(SH):]
        if component in NOT_CONSTRAINTS or component in TARGETS:
            continue
        parsed = parse_constraint(g, node, component, value)
        if isinstance(parsed, str):
            not_checked.append({"shape": shape, "path": path, "component": component, "reason": parsed})
        else:
            constraints.append(parsed)
    return constraints


def specs_from_graph(g: Graph) -> tuple[list[ShapeSpec], list[dict]]:
    """ShapeSpecs for every sh:NodeShape with sh:targetClass, plus what cannot be checked."""
    specs, not_checked = [], []
    for shape_node in sorted(set(g.subjects(RDF.type, URIRef(SH + "NodeShape")))):
        shape = node_id(shape_node)
        targets = sorted(str(t) for t in g.objects(shape_node, URIRef(SH + "targetClass")))
        if not targets:
            not_checked.append({"shape": shape, "path": None, "component": "target",
                                "reason": "only sh:targetClass targets are supported"})
            continue
        severity = g.value(shape_node, URIRef(SH + "severity"))
        properties = [PropertySpec(None, constraints_of(g, shape_node, shape, None, not_checked))]
        for ps in sorted(g.objects(shape_node, URIRef(SH + "property"))):
            if g.value(ps, URIRef(SH + "deactivated")) == Literal(True):
                continue
            path = g.value(ps, URIRef(SH + "path"))
            if not isinstance(path, URIRef):
                not_checked.append({"shape": shape, "path": None, "component": "path",
                                    "reason": "only predicate paths are supported"})
                continue
            properties.append(PropertySpec(str(path), constraints_of(g, ps, shape, str(path), not_checked)))
        # Blank node order changes between parses: sort for a stable report.
        properties.sort(key=lambda p: (p.path or "", [(c.component, c.text) for c in p.constraints]))
        closed = g.value(shape_node, URIRef(SH + "closed")) == Literal(True)
        ignored_node = g.value(shape_node, URIRef(SH + "ignoredProperties"))
        ignored = [str(i) for i in (read_list(g, ignored_node) or [])] if ignored_node is not None else []
        for target in targets:
            specs.append(ShapeSpec(shape=shape, source="found", target_class=target,
                                   severity=str(severity).removeprefix(SH) if severity else "Violation",
                                   properties=properties,   # path-only ones still count for sh:closed
                                   closed=closed, ignored_properties=ignored))
    not_checked.sort(key=lambda n: (n["shape"] or "", n["path"] or "", n["component"]))
    return specs, not_checked

"""shapes.ttl: draft SHACL shapes inferred from the profiles.

They describe what was observed in a sample, not rules: every property shape
has sh:severity sh:Info and carries its evidence (baq:support). Decisions are
made by `constraints_for` (pure, thresholds in thresholds.py); `render` only
turns them into RDF with rdflib, which guarantees valid Turtle.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from rdflib import BNode, Graph, Literal, Namespace, URIRef
from rdflib.namespace import RDF, RDFS, SH, XSD

from baqueano import REPO_URL
from baqueano.generate import thresholds as th
from baqueano.generate.names import identifier, unique_map
from baqueano.model import ClassProfile, Discovery, PropertyProfile
from baqueano.vocabularies import KNOWN

logger = logging.getLogger(__name__)

BAQ = Namespace(f"{REPO_URL}#")
SHAPE_BASE = "urn:baqueano:shape:"

# Object kinds observed -> sh:nodeKind value.
NODE_KINDS = {
    frozenset({"uri"}): SH.IRI,
    frozenset({"literal"}): SH.Literal,
    frozenset({"bnode"}): SH.BlankNode,
    frozenset({"uri", "literal"}): SH.IRIOrLiteral,
    frozenset({"uri", "bnode"}): SH.BlankNodeOrIRI,
    frozenset({"bnode", "literal"}): SH.BlankNodeOrLiteral,
}


@dataclass
class PropertyConstraints:
    path: str
    support: float
    min_count: bool = False
    max_count: bool = False
    datatype: str | None = None
    sh_class: str | None = None
    node_kind: URIRef | None = None
    languages: list[str] = field(default_factory=list)


def top_share(counts: dict[str, int], total: int) -> tuple[str | None, float]:
    """Most frequent key and its share of `total`."""
    if not counts or total <= 0:
        return None, 0.0
    key = max(counts, key=lambda k: (counts[k], k))
    return key, counts[key] / total


def constraints_for(pp: PropertyProfile) -> PropertyConstraints | None:
    """What the sample supports for one property; None when it is too rare."""
    if pp.support < th.PROPERTY_MIN_SUPPORT:
        logger.debug("shape: skip %s, support %.2f < %.2f", pp.path, pp.support, th.PROPERTY_MIN_SUPPORT)
        return None
    c = PropertyConstraints(path=pp.path, support=pp.support)
    c.min_count = pp.support >= th.MIN_COUNT_SUPPORT
    c.max_count = pp.max_values_per_subject == 1

    total = pp.iri_objects + pp.literal_objects + pp.bnode_objects
    if total and pp.literal_objects / total >= th.KIND_SHARE:
        datatype, share = top_share(pp.datatypes, pp.literal_objects)
        if share >= th.DATATYPE_SHARE:
            c.datatype = datatype
        logger.debug("shape: %s datatype %s covers %.2f (threshold %.2f)", pp.path, datatype, share,
                     th.DATATYPE_SHARE)
    if total and pp.iri_objects / total >= th.KIND_SHARE:
        cls, share = top_share(pp.target_classes, pp.objects_checked)
        if share >= th.CLASS_SHARE:
            c.sh_class = cls
        logger.debug("shape: %s class %s covers %.2f of %d checked (threshold %.2f)", pp.path, cls, share,
                     pp.objects_checked, th.CLASS_SHARE)
    if c.datatype is None and c.sh_class is None:
        kinds = frozenset(k for k, n in (("uri", pp.iri_objects), ("literal", pp.literal_objects),
                                         ("bnode", pp.bnode_objects)) if n)
        c.node_kind = NODE_KINDS.get(kinds)
    c.languages = sorted(pp.languages, key=lambda lang: (-pp.languages[lang], lang))
    return c


def shape_names(profiles: list[ClassProfile]) -> dict[str, str]:
    """{class IRI: shape IRI}, e.g. urn:baqueano:shape:Person (unique)."""
    names = unique_map([p.class_iri for p in profiles], identifier, separator="_")
    return {cls: SHAPE_BASE + name for cls, name in names.items()}


def add_list(g: Graph, id_prefix: str, items: list) -> BNode:
    """An rdf:List with deterministic blank node ids; returns its head."""
    cells = [BNode(f"{id_prefix}{i}") for i in range(len(items))]
    for i, (cell, item) in enumerate(zip(cells, items)):
        g.add((cell, RDF.first, item))
        g.add((cell, RDF.rest, cells[i + 1] if i + 1 < len(cells) else RDF.nil))
    return cells[0]


def add_target(g: Graph, shape: URIRef, class_iri: str, class_property: str) -> None:
    """sh:targetClass means rdf:type; any other class property needs a SPARQL target (SHACL-AF)."""
    if class_property == str(RDF.type):
        g.add((shape, SH.targetClass, URIRef(class_iri)))
        return
    target = BNode(f"{shape.split(':')[-1]}_target")
    g.add((shape, SH.target, target))
    g.add((target, RDF.type, SH.SPARQLTarget))
    g.add((target, SH.select, Literal(f"SELECT ?this WHERE {{ ?this <{class_property}> <{class_iri}> }}")))


def add_node_shape(g: Graph, shape: URIRef, prof: ClassProfile, class_property: str = str(RDF.type)) -> None:
    g.add((shape, RDF.type, SH.NodeShape))
    add_target(g, shape, prof.class_iri, class_property)
    g.add((shape, BAQ.sampleSize, Literal(prof.sample_size)))
    g.add((shape, BAQ.sampleMethod, Literal(prof.sample_method)))
    if prof.truncated:
        g.add((shape, BAQ.truncated, Literal(True)))
    g.add((shape, RDFS.comment, Literal(
        f"Inferred by Baqueano from a sample of {prof.sample_size} instances: "
        "it describes what was observed, not rules.")))

    # Blank node ids derived from the shape and position, so that the same
    # discovery always serializes to the same Turtle (diffable between runs).
    shape_id = shape.split(":")[-1]
    for i, pp in enumerate(prof.properties):
        if pp.path == class_property:      # already expressed by the target
            continue
        c = constraints_for(pp)
        if c is None:
            continue
        node = BNode(f"{shape_id}_p{i:03d}")
        g.add((shape, SH.property, node))
        g.add((node, SH.path, URIRef(c.path)))
        if c.datatype:
            g.add((node, SH.datatype, URIRef(c.datatype)))
        if c.sh_class:
            g.add((node, SH["class"], URIRef(c.sh_class)))
        if c.node_kind is not None:
            g.add((node, SH.nodeKind, c.node_kind))
        if c.min_count:
            g.add((node, SH.minCount, Literal(1)))
        if c.max_count:
            g.add((node, SH.maxCount, Literal(1)))
        if c.languages:
            g.add((node, SH.languageIn, add_list(g, f"{node}_lang", [Literal(x) for x in c.languages])))
        g.add((node, SH.severity, SH.Info))
        g.add((node, BAQ.support, Literal(round(c.support, 4), datatype=XSD.decimal)))


def render(discovery: Discovery) -> str:
    g = Graph(bind_namespaces="none")   # only our prefixes, same as the generated queries
    for ns, (prefix, _) in KNOWN.items():
        g.bind(prefix, Namespace(ns))
    g.bind("baq", BAQ)
    names = shape_names(discovery.profiles)
    for prof in discovery.profiles:
        add_node_shape(g, URIRef(names[prof.class_iri]), prof, discovery.class_property)
    header = (f"# Draft SHACL shapes inferred by Baqueano from {discovery.endpoint}\n"
              "# Observations from a sample, not rules: every constraint has sh:severity sh:Info\n"
              "# and baq:support (share of sampled instances that have the property).\n\n")
    return header + g.serialize(format="turtle")

"""schema.mmd: Mermaid classDiagram of the profiled classes and their links.

Classes: profiled classes and link targets, most populated first, capped at
DIAGRAM_MAX_CLASSES. Attributes: mostly-literal properties with their main
datatype. Edges: links with support >= DIAGRAM_MIN_SUPPORT between shown
classes, labelled with the property.
"""

from __future__ import annotations

from baqueano.generate import thresholds as th
from baqueano.generate.names import identifier, unique_map
from baqueano.model import ClassProfile, Discovery
from baqueano.profiling import RDF_TYPE
from baqueano.vocabularies import shorten


def classes_to_show(discovery: Discovery) -> list[str]:
    """Profiled classes and link targets, in class-count order, capped."""
    wanted = {p.class_iri for p in discovery.profiles}
    wanted |= {link.target_class for link in discovery.links if link.support >= th.DIAGRAM_MIN_SUPPORT}
    order = {c.iri: i for i, c in enumerate(discovery.classes)}
    ranked = sorted(wanted, key=lambda iri: (order.get(iri, len(order)), iri))
    return ranked[:th.DIAGRAM_MAX_CLASSES]


def attributes(prof: ClassProfile) -> list[str]:
    """'+datatype name' for mostly-literal properties."""
    lines = []
    for pp in prof.properties:
        if pp.path == RDF_TYPE or pp.support < th.DIAGRAM_MIN_SUPPORT:
            continue
        if pp.literal_objects == 0 or pp.literal_objects < pp.iri_objects + pp.bnode_objects:
            continue
        datatype = max(pp.datatypes, key=lambda d: (pp.datatypes[d], d)) if pp.datatypes else None
        type_name = identifier(datatype) if datatype else "literal"
        lines.append(f"+{type_name} {identifier(pp.path)}")
    return lines[:th.DIAGRAM_MAX_ATTRIBUTES]


def render(discovery: Discovery) -> str:
    shown = classes_to_show(discovery)
    ids = unique_map(shown, identifier, separator="_")
    profiles = {p.class_iri: p for p in discovery.profiles}

    out = ["%% Classes and links discovered by Baqueano (from samples).",
           f"%% Endpoint: {discovery.endpoint}",
           "classDiagram"]
    if not shown:
        out.append("  %% no profiled classes")
    for iri in shown:
        out.append(f'  class {ids[iri]}["{shorten(iri).strip("<>")}"]')
        if iri in profiles:
            out.extend(f"  {ids[iri]} : {attr}" for attr in attributes(profiles[iri]))
    for link in discovery.links:
        if link.support < th.DIAGRAM_MIN_SUPPORT or link.source_class not in ids or link.target_class not in ids:
            continue
        out.append(f"  {ids[link.source_class]} --> {ids[link.target_class]} : {identifier(link.path)}")
    return "\n".join(out) + "\n"

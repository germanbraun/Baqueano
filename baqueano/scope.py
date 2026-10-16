"""GRAPH <iri> wrapping when --graph is set.

Every step builds its graph patterns through `where`, so scoping lives in one
place.
"""

from __future__ import annotations

from baqueano.vocabularies import RDF_TYPE


def is_a(subject: str, cls: str, class_property: str) -> str:
    """Triple pattern 'subject is an instance of cls': '?s a ?class', or with
    --class-property, '?s <P> ?class'. `cls` is a variable or a written IRI."""
    if class_property == RDF_TYPE:
        return f"{subject} a {cls}"
    return f"{subject} <{class_property}> {cls}"


def where(pattern: str, graph: str | None) -> str:
    """Return `pattern`, wrapped in GRAPH <graph> { ... } when a graph is set."""
    if graph is None:
        return pattern
    return f"GRAPH <{graph}> {{ {pattern} }}"

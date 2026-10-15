"""GRAPH <iri> wrapping when --graph is set.

Every step builds its graph patterns through `where`, so scoping lives in one
place.
"""

from __future__ import annotations


def where(pattern: str, graph: str | None) -> str:
    """Return `pattern`, wrapped in GRAPH <graph> { ... } when a graph is set."""
    if graph is None:
        return pattern
    return f"GRAPH <{graph}> {{ {pattern} }}"

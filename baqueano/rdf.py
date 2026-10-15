"""Parsing RDF documents returned by the endpoint (pure: text in, Graph out)."""

from __future__ import annotations

import logging

from rdflib import Graph

logger = logging.getLogger(__name__)

# Content type fragment -> rdflib parser format.
RDF_FORMATS = {
    "turtle": "turtle",
    "n-triples": "nt",
    "rdf+xml": "xml",
    "ld+json": "json-ld",
    "trig": "trig",
}


def rdf_format(content_type: str | None) -> str | None:
    """rdflib format for a Content-Type header, or None if it is not RDF."""
    if not content_type:
        return None
    content_type = content_type.lower()
    for fragment, fmt in RDF_FORMATS.items():
        if fragment in content_type:
            return fmt
    return None


def parse_rdf(text: str, content_type: str | None) -> Graph | None:
    """Parse `text` according to its content type; None if not RDF or invalid."""
    fmt = rdf_format(content_type)
    if fmt is None:
        logger.debug("content type %r is not RDF", content_type)
        return None
    graph = Graph()
    try:
        graph.parse(data=text, format=fmt)
    except Exception as e:  # rdflib raises many different parser errors
        logger.debug("could not parse as %s: %s", fmt, e)
        return None
    return graph

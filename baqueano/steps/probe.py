"""Step 1: does the endpoint answer, and does it describe itself?

- ASK { ?s ?p ?o } confirms the endpoint answers (scoped with --graph).
- A GET without query, Accept: text/turtle, tries to fetch the Service
  Description. Its Server header is kept as a hint of the engine.
"""

from __future__ import annotations

import logging

from rdflib import Graph, URIRef
from rdflib.namespace import RDF

from baqueano import model, scope
from baqueano.context import Context, step_status
from baqueano.model import StepResult

logger = logging.getLogger(__name__)

NAME = "probe"
SD_STEP = "probe:service-description"
SD_ACCEPT = "text/turtle"
SD_SERVICE = URIRef("http://www.w3.org/ns/sparql-service-description#Service")

# Content type fragment -> rdflib parser format.
RDF_FORMATS = {
    "turtle": "turtle",
    "n-triples": "nt",
    "rdf+xml": "xml",
    "ld+json": "json-ld",
    "trig": "trig",
}


def ask_query(graph: str | None) -> str:
    return f"ASK {{ {scope.where('?s ?p ?o', graph)} }}"


def rdf_format(content_type: str | None) -> str | None:
    """rdflib format for a Content-Type header, or None if it is not RDF."""
    if not content_type:
        return None
    content_type = content_type.lower()
    for fragment, fmt in RDF_FORMATS.items():
        if fragment in content_type:
            return fmt
    return None


def has_service_description(text: str, content_type: str | None) -> bool:
    """True if `text` is RDF containing an sd:Service."""
    fmt = rdf_format(content_type)
    if fmt is None:
        logger.debug("service description: content type %r is not RDF", content_type)
        return False
    graph = Graph()
    try:
        graph.parse(data=text, format=fmt)
    except Exception as e:  # rdflib raises many different parser errors
        logger.debug("service description: could not parse as %s: %s", fmt, e)
        return False
    return (None, RDF.type, SD_SERVICE) in graph


def run(client, ctx: Context) -> StepResult:
    discovery = ctx.discovery
    graph = ctx.settings.graph

    ask = client.query(NAME, ask_query(graph))
    if ask.status != "ok":
        return StepResult(NAME, step_status(ask.status), f"endpoint did not answer: {ask.error}")
    if ask.boolean is None:
        return StepResult(NAME, model.ERROR, "ASK query did not return a boolean")

    doc = client.get_document(SD_STEP, SD_ACCEPT)
    discovery.server_header = doc.server_header
    if doc.status == "ok":
        discovery.has_service_description = has_service_description(doc.text or "", doc.content_type)
    else:
        logger.debug("no service description: %s", doc.error)

    parts = ["endpoint answers"]
    if not ask.boolean:
        where = f"in graph <{graph}>" if graph else "in the endpoint"
        parts.append(f"but found no triples {where}")
    parts.append("service description found" if discovery.has_service_description
                 else "no service description")
    if discovery.server_header:
        parts.append(f"server: {discovery.server_header}")
    return StepResult(NAME, model.OK, "; ".join(parts))

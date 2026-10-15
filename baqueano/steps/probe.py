"""Step 1: does the endpoint answer, and does it describe itself?

- ASK { ?s ?p ?o } confirms the endpoint answers (scoped with --graph).
- A GET without query, Accept: text/turtle, tries to fetch the Service
  Description. Its Server header is kept as a hint of the engine.
"""

from __future__ import annotations

import logging

from rdflib import URIRef
from rdflib.namespace import RDF

from baqueano import model, scope
from baqueano.context import Context, step_status
from baqueano.model import StepResult
from baqueano.rdf import parse_rdf

logger = logging.getLogger(__name__)

NAME = "probe"
SD_STEP = "probe:service-description"
SD_ACCEPT = "text/turtle"
SD_SERVICE = URIRef("http://www.w3.org/ns/sparql-service-description#Service")


def ask_query(graph: str | None) -> str:
    return f"ASK {{ {scope.where('?s ?p ?o', graph)} }}"


def failure_hint(status: str, http_status: int | None) -> str:
    """What the user can do when the probe fails."""
    if status == "timeout":
        return "the endpoint is slow or unreachable; try a larger --timeout"
    if status == "budget_exhausted":
        return "--budget is too small to even start"
    if status == "parse_error":
        return "the URL answered, but not with SPARQL results: is it the SPARQL endpoint URL?"
    if http_status in (401, 403):
        return "the endpoint needs authentication: set BAQUEANO_HEADER_AUTHORIZATION (or --header)"
    if http_status == 404:
        return "nothing at that URL: check the endpoint path (often /sparql)"
    if http_status == 400:
        return "the endpoint rejected a plain ASK query: is it a SPARQL 1.1 endpoint?"
    if http_status is not None and http_status >= 500:
        return "the server failed; it may be down or overloaded, try again later"
    if http_status is None:
        return "could not connect: check the URL, the network and any proxy"
    return "see queries.log for the full exchange"


def has_service_description(text: str, content_type: str | None) -> bool:
    """True if `text` is RDF containing an sd:Service."""
    graph = parse_rdf(text, content_type)
    return graph is not None and (None, RDF.type, SD_SERVICE) in graph


def run(client, ctx: Context) -> StepResult:
    discovery = ctx.discovery
    graph = ctx.settings.graph

    ask = client.query(NAME, ask_query(graph))
    if ask.status != "ok":
        hint = failure_hint(ask.status, ask.http_status)
        return StepResult(NAME, step_status(ask.status), f"endpoint did not answer: {ask.error} -> {hint}")
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

"""Every query a step sends must be valid SPARQL, with and without --graph."""

import pytest
from rdflib.plugins.sparql import prepareQuery

from baqueano.steps import classes, graphs, probe, profile, shapes_found, vocab, void

GRAPH = "http://example.org/graph/1"
IRIS = ["http://ex/a", "http://ex/b"]


def named(name, build):
    build.__qualname__ = name
    return build


QUERY_BUILDERS = [
    probe.ask_query,
    void.datasets_query,
    void.partitions_query,
    shapes_found.list_query,
    shapes_found.copy_query,
    graphs.count_query,
    classes.counts_query,
    classes.sample_query,
    vocab.ontologies_query,
    named("vocab.labels_query", lambda g: vocab.labels_query(IRIS, g)),
    named("profile.sample_query", lambda g: profile.sample_query("http://ex/C", 200, g)),
    named("profile.triples_query", lambda g: profile.triples_query(IRIS, g)),
    named("profile.types_query", lambda g: profile.types_query(IRIS, g)),
]


@pytest.mark.parametrize("build", QUERY_BUILDERS, ids=lambda f: f.__qualname__)
@pytest.mark.parametrize("graph", [None, GRAPH])
def test_query_parses(build, graph):
    query = build(graph)
    prepareQuery(query)
    if graph:
        assert f"GRAPH <{GRAPH}>" in query


def test_graphs_query_parses():
    prepareQuery(graphs.graphs_query())

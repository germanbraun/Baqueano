"""Every query a step sends must be valid SPARQL, with and without --graph."""

import pytest
from rdflib.plugins.sparql import prepareQuery

from baqueano.steps import classes, graphs, probe, shapes_found, void

GRAPH = "http://example.org/graph/1"

QUERY_BUILDERS = [
    probe.ask_query,
    void.datasets_query,
    void.partitions_query,
    shapes_found.list_query,
    shapes_found.copy_query,
    graphs.count_query,
    classes.counts_query,
    classes.sample_query,
]


@pytest.mark.parametrize("build", QUERY_BUILDERS, ids=lambda f: f"{f.__module__}.{f.__name__}")
@pytest.mark.parametrize("graph", [None, GRAPH])
def test_query_parses(build, graph):
    query = build(graph)
    prepareQuery(query)
    if graph:
        assert f"GRAPH <{GRAPH}>" in query


def test_graphs_query_parses():
    prepareQuery(graphs.graphs_query())

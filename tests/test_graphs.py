from baqueano.steps import graphs
from tests.fakes import FakeClient, budget_exhausted, http_error, iri, lit, select, timeout
from tests.helpers import make_ctx

XSD_INT = "http://www.w3.org/2001/XMLSchema#integer"
GRAPH_ROWS = [{"g": iri("http://ex/g1")}, {"g": iri("http://ex/g2")}]


def count(n):
    return select([{"n": lit(str(n), XSD_INT)}])


def test_graphs_and_exact_count():
    client = FakeClient({graphs.NAME: select(GRAPH_ROWS), graphs.COUNT_STEP: count(1234)})
    ctx = make_ctx()
    result = graphs.run(client, ctx)
    assert result.status == "ok"
    assert ctx.discovery.graphs == ["http://ex/g1", "http://ex/g2"]
    assert (ctx.discovery.triple_count, ctx.discovery.triple_count_exact) == (1234, True)


def test_graph_scope_skips_listing():
    client = FakeClient({graphs.COUNT_STEP: count(10)})
    ctx = make_ctx(graph="http://ex/g1")
    result = graphs.run(client, ctx)
    assert result.status == "ok"
    assert ctx.discovery.graphs == ["http://ex/g1"]
    assert client.queries_for(graphs.NAME) == []
    assert "GRAPH <http://ex/g1>" in client.queries_for(graphs.COUNT_STEP)[0]


def test_count_timeout_without_void_is_unknown():
    client = FakeClient({graphs.NAME: select(GRAPH_ROWS), graphs.COUNT_STEP: timeout()})
    ctx = make_ctx()
    result = graphs.run(client, ctx)
    assert result.status == "timeout"
    assert ctx.discovery.triple_count is None
    assert ctx.discovery.graphs == ["http://ex/g1", "http://ex/g2"]   # graphs kept
    assert "unknown" in result.message


def test_count_timeout_falls_back_to_void():
    client = FakeClient({graphs.NAME: select([]), graphs.COUNT_STEP: timeout()})
    ctx = make_ctx(void={"triples": 999})
    result = graphs.run(client, ctx)
    assert result.status == "sampled"
    assert (ctx.discovery.triple_count, ctx.discovery.triple_count_exact) == (999, False)


def test_worst_status_wins():
    client = FakeClient({graphs.NAME: budget_exhausted(), graphs.COUNT_STEP: timeout()})
    assert graphs.run(client, make_ctx()).status == "skipped"


def test_limit_reached_is_reported():
    rows = [{"g": iri(f"http://ex/g{i}")} for i in range(graphs.GRAPHS_LIMIT)]
    client = FakeClient({graphs.NAME: select(rows), graphs.COUNT_STEP: count(1)})
    assert "there may be more" in graphs.run(client, make_ctx()).message


def test_engine_without_named_graphs_is_unsupported_not_error():
    client = FakeClient({graphs.NAME: http_error(400), graphs.COUNT_STEP: count(9)})
    ctx = make_ctx()
    result = graphs.run(client, ctx)
    assert result.status == "unsupported"
    assert "named graphs not supported" in result.message
    assert ctx.discovery.triple_count == 9

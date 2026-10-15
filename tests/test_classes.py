from baqueano.model import ClassInfo
from baqueano.steps import classes
from tests.fakes import FakeClient, bnode, http_error, iri, lit, select, timeout
from tests.helpers import make_ctx

XSD_INT = "http://www.w3.org/2001/XMLSchema#integer"
COUNT_ROWS = [
    {"class": iri("http://ex/Place"), "n": lit("5", XSD_INT)},
    {"class": iri("http://ex/Person"), "n": lit("20", XSD_INT)},
    {"class": bnode("weird"), "n": lit("1", XSD_INT)},          # blank-node class: ignored
]


def test_exact_counts_sorted():
    client = FakeClient({classes.NAME: select(COUNT_ROWS)})
    ctx = make_ctx()
    result = classes.run(client, ctx)
    assert result.status == "ok"
    assert ctx.discovery.classes == [ClassInfo("http://ex/Person", 20, True), ClassInfo("http://ex/Place", 5, True)]
    assert client.queries_for(classes.SAMPLE_STEP) == []


def test_timeout_falls_back_to_void_partitions():
    client = FakeClient({classes.NAME: timeout()})
    ctx = make_ctx(void={"class_partitions": {"http://ex/A": 3, "http://ex/B": 30, "http://ex/C": None}})
    result = classes.run(client, ctx)
    assert result.status == "sampled"
    assert [c.iri for c in ctx.discovery.classes] == ["http://ex/B", "http://ex/A", "http://ex/C"]
    assert all(not c.count_exact for c in ctx.discovery.classes)
    assert client.queries_for(classes.SAMPLE_STEP) == []


def test_timeout_falls_back_to_sample():
    client = FakeClient({classes.NAME: timeout(),
                         classes.SAMPLE_STEP: select([{"class": iri("http://ex/A")}, {"class": iri("http://ex/B")}])})
    ctx = make_ctx()
    result = classes.run(client, ctx)
    assert result.status == "sampled"
    assert ctx.discovery.classes == [ClassInfo("http://ex/A", None, False), ClassInfo("http://ex/B", None, False)]
    assert "without counts" in result.message


def test_both_fail():
    client = FakeClient({classes.NAME: timeout(), classes.SAMPLE_STEP: http_error(500)})
    ctx = make_ctx()
    result = classes.run(client, ctx)
    assert result.status == "error"
    assert ctx.discovery.classes == []


def test_graph_scope_in_both_queries():
    client = FakeClient({classes.NAME: timeout(), classes.SAMPLE_STEP: select([])})
    classes.run(client, make_ctx(graph="http://ex/g"))
    for step in (classes.NAME, classes.SAMPLE_STEP):
        assert "GRAPH <http://ex/g>" in client.queries_for(step)[0]

from rdflib import Graph

from baqueano.steps import shapes_found
from tests.fakes import FakeClient, bnode, iri, rdf, select, timeout
from tests.helpers import make_ctx

SHAPES_TTL = """
@prefix sh: <http://www.w3.org/ns/shacl#> .
@prefix ex: <http://ex/> .
ex:PersonShape a sh:NodeShape ;
    sh:targetClass ex:Person ;
    sh:property [ sh:path ex:name ; sh:minCount 1 ] .
"""

ROWS = [
    {"shape": iri("http://ex/PersonShape"), "target": iri("http://ex/Person")},
    {"shape": iri("http://ex/PersonShape"), "target": iri("http://ex/Person")},   # duplicate
    {"shape": bnode("b1")},
]


def test_shapes_from_rows():
    assert shapes_found.shapes_from_rows(ROWS) == [
        {"shape": "http://ex/PersonShape", "target_class": "http://ex/Person"},
        {"shape": "_:b1", "target_class": None},
    ]


def test_no_shapes_is_ok_without_construct():
    client = FakeClient({shapes_found.LIST_STEP: select([])})
    ctx = make_ctx()
    result = shapes_found.run(client, ctx)
    assert result.status == "ok"
    assert ctx.discovery.found_shapes == []
    assert client.queries_for(shapes_found.COPY_STEP) == []


def test_shapes_copied_as_valid_turtle():
    client = FakeClient({shapes_found.LIST_STEP: select(ROWS[:1]), shapes_found.COPY_STEP: rdf(SHAPES_TTL)})
    ctx = make_ctx()
    result = shapes_found.run(client, ctx)
    assert result.status == "ok"
    assert "1 shape(s), 5 triples copied" in result.message
    copied = Graph().parse(data=ctx.discovery.found_shapes_ttl, format="turtle")
    assert len(copied) == 5


def test_construct_timeout_keeps_shape_list():
    client = FakeClient({shapes_found.LIST_STEP: select(ROWS), shapes_found.COPY_STEP: timeout()})
    ctx = make_ctx()
    result = shapes_found.run(client, ctx)
    assert result.status == "timeout"
    assert len(ctx.discovery.found_shapes) == 2
    assert ctx.discovery.found_shapes_ttl is None


def test_unparseable_construct_answer():
    client = FakeClient({shapes_found.LIST_STEP: select(ROWS),
                         shapes_found.COPY_STEP: rdf("<html>oops</html>", "text/html")})
    result = shapes_found.run(client, make_ctx())
    assert result.status == "error"

from baqueano.steps import void
from tests.fakes import FakeClient, bnode, iri, lit, select, timeout
from tests.helpers import make_ctx

V = void.VOID
XSD_INT = "http://www.w3.org/2001/XMLSchema#integer"

DATASET_ROWS = [
    {"ds": iri("http://ex/ds"), "p": iri(V + "triples"), "o": lit("1000", XSD_INT)},
    {"ds": iri("http://ex/ds"), "p": iri(V + "vocabulary"), "o": iri("https://schema.org/")},
    {"ds": iri("http://ex/ds"), "p": iri(V + "subset"), "o": bnode("sub")},
    {"ds": bnode("sub"), "p": iri(V + "triples"), "o": lit("200", XSD_INT)},
]
PARTITION_ROWS = [
    {"class": iri("http://ex/Person"), "entities": lit("50", XSD_INT)},
    {"class": iri("http://ex/Person"), "entities": lit("80", XSD_INT)},   # also in a subset
    {"class": iri("http://ex/Place")},                                     # no void:entities
]


def test_summarize():
    summary = void.summarize(DATASET_ROWS, PARTITION_ROWS)
    assert summary["triples"] == 1000
    assert summary["vocabularies"] == ["https://schema.org/"]
    assert set(summary["datasets"]) == {"http://ex/ds", "_:sub"}
    assert summary["class_partitions"] == {"http://ex/Person": 80, "http://ex/Place": None}


def test_no_void_is_ok_and_skips_partitions():
    client = FakeClient({void.NAME: select([])})
    ctx = make_ctx()
    result = void.run(client, ctx)
    assert result.status == "ok"
    assert ctx.discovery.void is None
    assert client.queries_for(void.PARTITIONS_STEP) == []


def test_void_found():
    client = FakeClient({void.NAME: select(DATASET_ROWS), void.PARTITIONS_STEP: select(PARTITION_ROWS)})
    ctx = make_ctx()
    result = void.run(client, ctx)
    assert result.status == "ok"
    assert ctx.discovery.void["triples"] == 1000
    assert "2 class partition(s)" in result.message


def test_partitions_timeout_keeps_datasets():
    client = FakeClient({void.NAME: select(DATASET_ROWS), void.PARTITIONS_STEP: timeout()})
    ctx = make_ctx()
    result = void.run(client, ctx)
    assert result.status == "timeout"
    assert ctx.discovery.void["triples"] == 1000
    assert ctx.discovery.void["class_partitions"] == {}


def test_void_query_timeout():
    result = void.run(FakeClient({void.NAME: timeout()}), make_ctx())
    assert result.status == "timeout"

from baqueano.model import ClassInfo
from baqueano.profiling import RDF_TYPE
from baqueano.steps import profile
from tests.fakes import FakeClient, bnode, budget_exhausted, iri, lit, select, timeout
from tests.helpers import make_ctx

EX = "http://ex/"
PERSON = EX + "Person"
NAME = EX + "name"


def label(part, cls=PERSON):
    return profile.step_label(cls, part)


def subjects(n, prefix="p"):
    return select([{"s": iri(f"{EX}{prefix}{i}")} for i in range(n)])


def name_rows(start, n, prefix="p"):
    return select([{"s": iri(f"{EX}{prefix}{i}"), "p": iri(NAME), "o": lit(f"n{i}")}
                   for i in range(start, start + n)])


def ctx_with(classes, sample=200, max_classes=30, graph=None):
    ctx = make_ctx(graph=graph)
    ctx.discovery.classes = classes
    ctx.settings.sample = sample
    ctx.settings.max_classes = max_classes
    return ctx


def test_subjects_are_batched_by_50():
    client = FakeClient({
        label("sample"): subjects(120),
        label("triples"): [name_rows(0, 50), name_rows(50, 50), name_rows(100, 20)],
    })
    ctx = ctx_with([ClassInfo(PERSON, 120, True)], sample=120)
    result = profile.run(client, ctx)
    assert result.status == "ok"
    triples_queries = client.queries_for(label("triples"))
    assert [q.count("<http://ex/p") for q in triples_queries] == [50, 50, 20]
    assert client.queries_for(label("sample")) == [f"SELECT ?s WHERE {{ ?s a <{PERSON}> }} LIMIT 120"]
    prof = ctx.discovery.profiles[0]
    assert prof.sample_size == 120
    assert prof.properties[0].support == 1.0


def test_failed_batch_drops_its_subjects():
    client = FakeClient({
        label("sample"): subjects(100),
        label("triples"): [name_rows(0, 50), timeout()],
    })
    ctx = ctx_with([ClassInfo(PERSON, 100, True)], sample=100)
    result = profile.run(client, ctx)
    assert result.status == "timeout"
    prof = ctx.discovery.profiles[0]
    assert prof.sample_size == 50           # only the subjects of the batch that answered
    assert prof.failed_batches == 1
    assert prof.properties[0].support == 1.0


def test_truncated_when_batch_hits_limit(monkeypatch):
    monkeypatch.setattr(profile, "TRIPLES_LIMIT", 3)
    client = FakeClient({label("sample"): subjects(3), label("triples"): name_rows(0, 3)})
    ctx = ctx_with([ClassInfo(PERSON, 3, True)])
    result = profile.run(client, ctx)
    assert ctx.discovery.profiles[0].truncated is True
    assert "1 truncated" in result.message


def test_object_types_are_looked_up_once_per_object():
    rows = [{"s": iri(EX + "p0"), "p": iri(EX + "knows"), "o": iri(EX + "p1")},
            {"s": iri(EX + "p1"), "p": iri(EX + "knows"), "o": iri(EX + "p0")},
            {"s": iri(EX + "p1"), "p": iri(EX + "likes"), "o": iri(EX + "p0")},
            {"s": iri(EX + "p0"), "p": iri(RDF_TYPE), "o": iri(PERSON)}]
    client = FakeClient({
        label("sample"): subjects(2),
        label("triples"): select(rows),
        label("types"): select([{"o": iri(EX + "p0"), "t": iri(PERSON)},
                                {"o": iri(EX + "p1"), "t": iri(PERSON)}]),
    })
    ctx = ctx_with([ClassInfo(PERSON, 2, True)])
    profile.run(client, ctx)
    types_query = client.queries_for(label("types"))[0]
    assert types_query.count(f"<{EX}p0>") == 1 and types_query.count(f"<{EX}p1>") == 1
    assert PERSON not in types_query.split("VALUES")[1].split("}")[0]   # rdf:type objects not checked
    likes = next(pp for pp in ctx.discovery.profiles[0].properties if pp.path == EX + "likes")
    assert likes.target_classes == {PERSON: 1}


def test_failed_type_lookup_leaves_objects_unchecked():
    rows = [{"s": iri(EX + "p0"), "p": iri(EX + "knows"), "o": iri(EX + "p1")}]
    client = FakeClient({label("sample"): subjects(1), label("triples"): select(rows), label("types"): timeout()})
    ctx = ctx_with([ClassInfo(PERSON, 1, True)])
    result = profile.run(client, ctx)
    assert result.status == "timeout"
    knows = ctx.discovery.profiles[0].properties[0]
    assert (knows.objects_checked, knows.target_classes) == (0, {})


def test_budget_exhaustion_stops_profiling():
    place = EX + "Place"
    client = FakeClient({
        label("sample"): subjects(1),
        label("triples"): name_rows(0, 1),
        label("sample", place): budget_exhausted(),
    })
    ctx = ctx_with([ClassInfo(PERSON, 9, True), ClassInfo(place, 5, True), ClassInfo(EX + "Thing", 1, True)])
    result = profile.run(client, ctx)
    assert result.status == "skipped"
    assert len(ctx.discovery.profiles) == 1
    assert "1 of 3 classes profiled" in result.message
    assert "budget ran out" in result.message
    assert client.queries_for(label("sample", EX + "Thing")) == []


def test_metadata_and_max_classes():
    owl_class = "http://www.w3.org/2002/07/owl#Class"
    place = EX + "Place"
    client = FakeClient({label("sample"): subjects(1), label("triples"): name_rows(0, 1)})
    ctx = ctx_with([ClassInfo(owl_class, 50, True), ClassInfo(PERSON, 9, True), ClassInfo(place, 5, True)],
                   max_classes=1)
    result = profile.run(client, ctx)
    assert [p.class_iri for p in ctx.discovery.profiles] == [PERSON]
    assert "1 metadata class(es) skipped" in result.message


def test_blank_node_instances_are_not_profiled_and_not_degraded():
    client = FakeClient({label("sample"): select([{"s": bnode("b1")}, {"s": bnode("b2")}])})
    ctx = ctx_with([ClassInfo(PERSON, 2, True)])
    result = profile.run(client, ctx)
    assert result.status == "ok"
    assert ctx.discovery.profiles == []


def test_label_properties_detected():
    rdfs_label = "http://www.w3.org/2000/01/rdf-schema#label"
    rows = [{"s": iri(EX + "p0"), "p": iri(rdfs_label), "o": lit("x")}]
    client = FakeClient({label("sample"): subjects(1), label("triples"): select(rows)})
    ctx = ctx_with([ClassInfo(PERSON, 1, True)])
    profile.run(client, ctx)
    assert ctx.discovery.label_properties == [rdfs_label]


def test_graph_scope():
    client = FakeClient({label("sample"): subjects(1), label("triples"): name_rows(0, 1)})
    profile.run(client, ctx_with([ClassInfo(PERSON, 1, True)], graph="http://ex/g"))
    for step in (label("sample"), label("triples")):
        assert "GRAPH <http://ex/g>" in client.queries_for(step)[0]

"""Class selection, sampling plans and the class property (v0.2 changes)."""

import pytest
from rdflib import Graph
from rdflib.namespace import RDF, SH
from rdflib.plugins.sparql import prepareQuery

from baqueano import scope, vocabularies as v
from baqueano.context import Settings
from baqueano.generate import queries, shapes
from baqueano.model import ClassInfo
from baqueano.profiling import RDF_TYPE, objects_to_check, triples_from_rows
from baqueano.steps import classes, links, profile, validate
from tests.fakes import FakeClient, iri, lit, select, timeout
from tests.helpers import make_ctx
from tests.sample_discovery import PERSON, S, sample_discovery

P31 = "http://www.wikidata.org/prop/direct/P31"
Q5 = "http://www.wikidata.org/entity/Q5"
EX = "http://ex/"


# -- helpers -----------------------------------------------------------------------

def test_expand():
    assert v.expand("wd:Q5") == Q5
    assert v.expand("wdt:P31") == P31
    assert v.expand("rdf:type") == RDF_TYPE
    assert v.expand("<http://ex/A>") == "http://ex/A"
    assert v.expand("http://ex/A") == "http://ex/A"
    assert v.expand("nope:A") is None
    assert v.expand("http://ex/a b") is None


def test_is_a():
    assert scope.is_a("?s", "?class", RDF_TYPE) == "?s a ?class"
    assert scope.is_a("?s", f"<{Q5}>", P31) == f"?s <{P31}> <{Q5}>"


def test_infrastructure():
    assert v.is_infrastructure("http://wikiba.se/ontology#BestRank")
    assert v.is_infrastructure("http://dbpedia.org/ontology/Image")
    assert not v.is_infrastructure("http://dbpedia.org/ontology/Person")


# -- class selection -----------------------------------------------------------------

def test_selection_order():
    classes_ = [ClassInfo("http://wikiba.se/ontology#BestRank", 900, True),
                ClassInfo("http://www.w3.org/2002/07/owl#Class", 800, True),
                ClassInfo("http://dbpedia.org/ontology/Image", 700, True),
                ClassInfo(EX + "Big", 600, True),
                ClassInfo(EX + "Small", 5, True),
                ClassInfo(EX + "Empty", 0, True)]
    chosen, metadata, moved = profile.classes_to_profile(classes_, 10, requested=[EX + "Small", EX + "Unlisted"])
    assert [c.iri for c in chosen] == [EX + "Small", EX + "Unlisted", EX + "Big",
                                       "http://wikiba.se/ontology#BestRank", "http://dbpedia.org/ontology/Image"]
    assert (metadata, moved) == (1, 2)
    assert chosen[1].count is None                         # requested but not listed


def test_selection_cap_drops_infrastructure_first():
    classes_ = [ClassInfo("http://wikiba.se/ontology#BestRank", 900, True), ClassInfo(EX + "A", 10, True)]
    chosen, _, _ = profile.classes_to_profile(classes_, 1)
    assert [c.iri for c in chosen] == [EX + "A"]


# -- sampling plans -----------------------------------------------------------------

def test_plan_all_when_exact_count_fits():
    assert profile.sample_plan(ClassInfo(EX + "C", 150, True), 200, 1) == ("all", [(0, 200)])


def test_plan_first_n_when_count_unknown_or_declared_small():
    assert profile.sample_plan(ClassInfo(EX + "C", None, False), 200, 1) == ("first-n", [(0, 200)])
    assert profile.sample_plan(ClassInfo(EX + "C", 150, False), 200, 1) == ("first-n", [(0, 200)])


def test_plan_random_offset_is_reproducible_and_in_range():
    info = ClassInfo(EX + "C", 50_000, True)
    method, plan = profile.sample_plan(info, 200, seed=1)
    assert method == "random-offset"
    assert len(plan) == profile.SAMPLE_BLOCKS and all(limit == 50 for _, limit in plan)
    assert all(0 <= offset <= 50_000 - 50 for offset, _ in plan)
    assert plan == sorted(plan) and len({o for o, _ in plan}) == profile.SAMPLE_BLOCKS
    assert profile.sample_plan(info, 200, seed=1) == (method, plan)           # same seed, same plan
    assert profile.sample_plan(info, 200, seed=2)[1] != plan                  # other seed, other plan


def test_plan_caps_offsets():
    _, plan = profile.sample_plan(ClassInfo(EX + "C", 10**9, True), 200, 1)
    assert max(o for o, _ in plan) <= profile.MAX_OFFSET


def subjects(prefix, n):
    return select([{"s": iri(f"{EX}{prefix}{i}")} for i in range(n)])


def big_ctx(class_property=RDF_TYPE):
    ctx = make_ctx()
    ctx.discovery.classes = [ClassInfo(EX + "C", 50_000, True)]
    ctx.settings = Settings(sample=200, class_property=class_property)
    return ctx


def test_random_offset_run_sends_offset_queries():
    label = profile.step_label(EX + "C", "sample")
    client = FakeClient({label: [subjects("a", 50), subjects("b", 50), subjects("c", 50), subjects("d", 50)],
                         profile.step_label(EX + "C", "triples"): select([])})
    ctx = big_ctx()
    result = profile.run(client, ctx)
    sent = client.queries_for(label)
    assert len(sent) == 4 and all(" OFFSET " in q and q.endswith("LIMIT 100") for q in sent)   # 2x oversampling
    assert result.status == "ok"
    prof = ctx.discovery.profiles[0]
    assert (prof.sample_method, prof.sample_size) == ("random-offset", 200)


def test_failed_blocks_are_dropped_without_degrading():
    label = profile.step_label(EX + "C", "sample")
    client = FakeClient({label: [subjects("a", 50), timeout(), subjects("c", 50), subjects("d", 50)],
                         profile.step_label(EX + "C", "triples"): select([])})
    ctx = big_ctx()
    assert profile.run(client, ctx).status == "ok"
    assert ctx.discovery.profiles[0].sample_size == 150


def test_all_blocks_fail_falls_back_to_first_n():
    label = profile.step_label(EX + "C", "sample")
    client = FakeClient({label: [timeout()] * 4 + [subjects("a", 200)],
                         profile.step_label(EX + "C", "triples"): select([])})
    ctx = big_ctx()
    profile.run(client, ctx)
    assert client.queries_for(label)[-1].endswith("} LIMIT 400")              # no OFFSET, 2x oversampling
    assert ctx.discovery.profiles[0].sample_method == "first-n"


# -- class property --------------------------------------------------------------------

def test_class_property_in_profile_queries():
    ctx = big_ctx(class_property=P31)
    ctx.settings.sample = 10
    ctx.discovery.classes = [ClassInfo(Q5, 5, True)]
    rows = [{"s": iri(EX + "a0"), "p": iri(P31), "o": iri(Q5)},
            {"s": iri(EX + "a0"), "p": iri(EX + "spouse"), "o": iri(EX + "b")}]
    client = FakeClient({profile.step_label(Q5, "sample"): subjects("a", 1),
                         profile.step_label(Q5, "triples"): select(rows),
                         profile.step_label(Q5, "types"): select([{"o": iri(EX + "b"), "t": iri(Q5)}])})
    profile.run(client, ctx)
    assert f"?s <{P31}> <{Q5}>" in client.queries_for(profile.step_label(Q5, "sample"))[0]
    types_q = client.queries_for(profile.step_label(Q5, "types"))[0]
    assert f"?o <{P31}> ?t" in types_q and f"<{Q5}>" not in types_q.split("VALUES")[1].split("}")[0]


def test_objects_to_check_skips_class_property():
    triples = triples_from_rows([{"s": iri(EX + "a"), "p": iri(P31), "o": iri(Q5)},
                                 {"s": iri(EX + "a"), "p": iri(RDF_TYPE), "o": iri(EX + "T")}])
    assert objects_to_check(triples, class_property=P31) == {RDF_TYPE: [EX + "T"]}


def test_classes_step_with_class_property_and_requested():
    ctx = make_ctx(void={"class_partitions": {EX + "A": 3}})
    ctx.settings.class_property = P31
    ctx.settings.classes = [Q5]
    client = FakeClient({classes.NAME: timeout(), classes.SAMPLE_STEP: select([{"class": iri(EX + "B")}])})
    result = classes.run(client, ctx)
    assert f"?s <{P31}> ?class" in client.queries_for(classes.NAME)[0]
    assert [c.iri for c in ctx.discovery.classes] == [EX + "B", Q5]           # VoID ignored: it means rdf:type
    assert "1 requested class(es) added without count" in result.message


def wikidata_discovery():
    d = sample_discovery()
    d.class_property = P31
    for prof in d.profiles:
        for pp in prof.properties:
            if pp.path == RDF_TYPE:
                pp.path = P31
    d.links = links.links_from_profiles(d.profiles, P31)
    return d


def test_generated_queries_use_class_property():
    files = queries.render(wikidata_discovery())
    for name, text in files.items():
        prepareQuery(text)
        assert " a " not in text.split("WHERE")[1], name
    assert "?person wdt:P31 schema:Person ." in files["12-person-table.rq"]
    assert "PREFIX wdt: <http://www.wikidata.org/prop/direct/>" in files["12-person-table.rq"]


def test_shapes_use_sparql_target_for_other_class_property():
    g = Graph().parse(data=shapes.render(wikidata_discovery()), format="turtle")
    shape = next(g.subjects(RDF.type, SH.NodeShape))
    assert g.value(shape, SH.targetClass) is None
    target = g.value(shape, SH.target)
    assert g.value(target, RDF.type) == SH.SPARQLTarget
    prepareQuery(str(g.value(target, SH.select)))
    assert P31 in str(g.value(target, SH.select))


def test_published_shapes_not_validated_with_other_class_property():
    d = wikidata_discovery()
    d.found_shapes_ttl = f"<http://ex/S> a <{SH.NodeShape}> ; <{SH.targetClass}> <{PERSON}> ."
    specs, not_checked = validate.found_specs(d)
    assert specs == [] and not_checked[0]["component"] == "targetClass"


@pytest.mark.parametrize("build", [
    lambda: classes.counts_query("http://ex/g", P31),
    lambda: classes.sample_query(None, P31),
    lambda: profile.sample_query(Q5, 50, "http://ex/g", P31, offset=1234),
    lambda: profile.types_query([EX + "a"], None, P31),
])
def test_new_queries_parse(build):
    prepareQuery(build())


def test_duplicate_rows_are_skipped_within_a_block():
    rows = [{"s": iri(EX + n)} for n in ("a", "a", "b", "b", "c", "d")]
    assert [r["s"]["value"] for r in profile.first_distinct(rows, 3)] == [EX + "a", EX + "b", EX + "c"]


def test_duplicates_do_not_shrink_the_sample():
    label = profile.step_label(EX + "C", "sample")
    doubled = lambda p: select([{"s": iri(f"{EX}{p}{i // 2}")} for i in range(100)])   # each instance twice
    client = FakeClient({label: [doubled("a"), doubled("b"), doubled("c"), doubled("d")],
                         profile.step_label(EX + "C", "triples"): select([])})
    ctx = big_ctx()
    profile.run(client, ctx)
    assert ctx.discovery.profiles[0].sample_size == 200


def test_type_checks_capped_and_given_to_common_properties_first():
    rows = [{"s": iri(f"{EX}s{i}"), "p": iri(EX + "common"), "o": iri(f"{EX}c{i}")} for i in range(30)]
    rows += [{"s": iri(EX + "s0"), "p": iri(EX + "rare"), "o": iri(f"{EX}r{i}")} for i in range(30)]
    checked = objects_to_check(triples_from_rows(rows), per_property=20, max_total=25)
    assert list(checked) == [EX + "common", EX + "rare"]
    assert (len(checked[EX + "common"]), len(checked[EX + "rare"])) == (20, 5)

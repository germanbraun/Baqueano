from baqueano.profiling import RDF_TYPE, Sample
from baqueano.steps import validate
from tests.fakes import FakeClient, iri, lit
from tests.helpers import make_ctx
from tests.sample_discovery import PERSON, PLACE, S, sample_discovery

FOUND = f"""
@prefix sh: <http://www.w3.org/ns/shacl#> .
<http://ex/PersonShape> a sh:NodeShape ; sh:targetClass <{PERSON}> ;
    sh:property [ sh:path <{S}email> ; sh:minCount 1 ] ;
    sh:property [ sh:path <{S}name> ; sh:qualifiedMinCount 1 ] .
<http://ex/OrgShape> a sh:NodeShape ; sh:targetClass <http://ex/Org> ; sh:nodeKind sh:IRI .
"""


def ctx_with_samples():
    ctx = make_ctx()
    ctx.discovery = sample_discovery()
    ctx.discovery.found_shapes_ttl = FOUND
    people = [f"http://ex/person/{i}" for i in range(4)]
    triples = [(p, RDF_TYPE, iri(PERSON)) for p in people]
    triples += [(p, S + "name", lit(f"n{i}")) for i, p in enumerate(people)]
    triples += [(people[0], S + "email", lit("a@x")), (people[1], S + "email", lit("b@x"))]
    triples += [(people[2], S + "birthDate", lit("1990-01-01", "http://www.w3.org/2001/XMLSchema#date")),
                (people[3], S + "birthDate", lit("not a date"))]
    ctx.samples[PERSON] = Sample(PERSON, people, triples)
    return ctx


def test_found_and_inferred_shapes_are_checked():
    ctx = ctx_with_samples()
    result = validate.run(FakeClient({}), ctx)
    assert result.status == "ok"
    found = [r for r in ctx.discovery.validation if r.source == "found"]
    assert [(r.path, r.component, r.violations) for r in found] == [(S + "email", "minCount", 2)]
    inferred = {(r.path, r.component): r for r in ctx.discovery.validation if r.source == "inferred"}
    birth_dt = inferred[(S + "birthDate", "datatype")]
    assert (birth_dt.violations, birth_dt.examples, birth_dt.severity) == (1, ["http://ex/person/3"], "Info")
    assert inferred[(S + "birthDate", "minCount")].violations == 2     # two sampled people lack it
    assert all(r.target_class == PERSON for r in ctx.discovery.validation)   # Place has no sample here
    assert ctx.discovery.validation_not_checked == [
        {"shape": "http://ex/PersonShape", "path": S + "name", "component": "qualifiedMinCount",
         "reason": "not supported by Baqueano's validator"}]
    assert "1 published shape target(s) not profiled" in result.message
    assert "1 constraint(s) not checked" in result.message


def test_nothing_profiled():
    result = validate.run(FakeClient({}), make_ctx())
    assert result.message == "nothing to validate (no class was profiled)"


def test_inferred_specs_match_shapes_ttl_decisions():
    specs = {s.target_class: s for s in validate.inferred_specs(sample_discovery())}
    person = {p.path: [c.component for c in p.constraints] for p in specs[PERSON].properties}
    assert person[S + "birthPlace"] == ["minCount", "maxCount", "class"]
    assert person[S + "knows"] == ["nodeKind"]
    assert person[S + "nick"] == ["datatype", "languageIn"]
    assert S + "faxNumber" not in person and RDF_TYPE not in person
    assert specs[PLACE].shape == "urn:baqueano:shape:Place"

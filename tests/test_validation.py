"""The SHACL Core subset validator, component by component."""

import re

import pytest
from rdflib import Graph

from baqueano.profiling import RDF_TYPE, Sample
from baqueano.validation import (Constraint, PropertySpec, ShapeSpec, check, specs_from_graph, term_key,
                                 to_term, validate)
from rdflib import Literal
from tests.fakes import bnode, iri, lit

XSD = "http://www.w3.org/2001/XMLSchema#"
EX = "http://ex/"


def c(component, parameter):
    return Constraint(component, parameter, str(parameter))


def run(constraint, values, types=None, checked=None):
    return check(constraint, values, types or {}, checked or set())


@pytest.mark.parametrize("constraint, values, expected", [
    (c("minCount", 1), [], "violation"),
    (c("minCount", 1), [lit("a")], "ok"),
    (c("maxCount", 1), [lit("a"), lit("b")], "violation"),
    (c("maxCount", 1), [], "ok"),
    (c("datatype", XSD + "string"), [lit("plain")], "ok"),                     # plain literal is xsd:string
    (c("datatype", XSD + "date"), [lit("2020-01-01", XSD + "date")], "ok"),
    (c("datatype", XSD + "date"), [lit("2020-01-01")], "violation"),
    (c("datatype", XSD + "string"), [iri(EX + "x")], "violation"),
    (c("nodeKind", "IRI"), [iri(EX + "x")], "ok"),
    (c("nodeKind", "IRI"), [bnode("b")], "violation"),
    (c("nodeKind", "BlankNodeOrIRI"), [bnode("b"), iri(EX + "x")], "ok"),
    (c("languageIn", ["en"]), [lit("hi", lang="en-GB")], "ok"),                # basic language range
    (c("languageIn", ["en"]), [lit("hola", lang="es")], "violation"),
    (c("languageIn", ["en"]), [lit("untagged")], "violation"),
    (c("in", {term_key(lit("a")), term_key(iri(EX + "b"))}), [lit("a"), iri(EX + "b")], "ok"),
    (c("in", {term_key(lit("a"))}), [lit("a", lang="en")], "violation"),
    (c("hasValue", iri(EX + "b")), [iri(EX + "a"), iri(EX + "b")], "ok"),
    (c("hasValue", iri(EX + "b")), [iri(EX + "a")], "violation"),
    (c("uniqueLang", True), [lit("a", lang="en"), lit("b", lang="EN")], "violation"),
    (c("uniqueLang", True), [lit("a", lang="en"), lit("b", lang="es"), lit("c")], "ok"),
    (c("pattern", (r"@example\.org$", 0)), [lit("ana@example.org")], "ok"),
    (c("pattern", (r"^A", re.IGNORECASE)), [lit("ana")], "ok"),
    (c("pattern", (r"^A", 0)), [bnode("b")], "violation"),
    (c("minLength", 3), [lit("ab")], "violation"),
    (c("maxLength", 3), [iri(EX + "x")], "violation"),                         # the IRI string is long
    (c("minInclusive", 18), [lit("18", XSD + "integer")], "ok"),
    (c("minExclusive", 18), [lit("18", XSD + "integer")], "violation"),
    (c("maxInclusive", 5), [lit("not a number")], "violation"),               # incomparable
])
def test_components(constraint, values, expected):
    assert run(constraint, values) == expected


def test_class_uses_fetched_types_and_reports_unknown():
    cls = c("class", EX + "Person")
    types = {EX + "p1": {EX + "Person"}, EX + "p2": {EX + "Robot"}}
    checked = {EX + "p1", EX + "p2"}
    assert run(cls, [iri(EX + "p1")], types, checked) == "ok"
    assert run(cls, [iri(EX + "p2")], types, checked) == "violation"
    assert run(cls, [iri(EX + "p9")], types, checked) == "unknown"            # types not fetched
    assert run(cls, [iri(EX + "p1"), iri(EX + "p9")], types, checked) == "unknown"
    assert run(cls, [iri(EX + "p2"), iri(EX + "p9")], types, checked) == "violation"
    assert run(cls, [lit("x")], types, checked) == "violation"


def test_values_with_empty_list_pass_per_value_constraints():
    assert run(c("datatype", XSD + "date"), []) == "ok"


def sample():
    triples = [
        (EX + "p1", RDF_TYPE, iri(EX + "Person")), (EX + "p1", EX + "name", lit("Ana")),
        (EX + "p2", RDF_TYPE, iri(EX + "Person")), (EX + "p2", EX + "name", lit("Bo")),
        (EX + "p2", EX + "name", lit("Bob")),
        (EX + "p3", RDF_TYPE, iri(EX + "Person")), (EX + "p3", EX + "nick", lit("C")),
    ]
    return Sample(EX + "Person", [EX + "p1", EX + "p2", EX + "p3"], triples)


def test_validate_counts_instances_and_keeps_examples():
    spec = ShapeSpec("http://ex/S", "found", EX + "Person", properties=[
        PropertySpec(EX + "name", [c("minCount", 1), c("maxCount", 1)])])
    results = {r.component: r for r in validate(spec, sample())}
    assert (results["minCount"].checked, results["minCount"].violations, results["minCount"].examples) == \
        (3, 1, [EX + "p3"])
    assert (results["maxCount"].violations, results["maxCount"].examples) == (1, [EX + "p2"])
    assert results["minCount"].path == EX + "name"


def test_node_level_and_closed():
    spec = ShapeSpec("http://ex/S", "found", EX + "Person", closed=True, ignored_properties=[RDF_TYPE],
                     properties=[PropertySpec(None, [c("nodeKind", "IRI")]), PropertySpec(EX + "name", [])])
    results = {r.component: r for r in validate(spec, sample())}
    assert results["nodeKind"].violations == 0 and results["nodeKind"].path is None
    assert (results["closed"].violations, results["closed"].examples) == (1, [EX + "p3"])   # nick not allowed


SHAPES = """
@prefix sh: <http://www.w3.org/ns/shacl#> .
@prefix ex: <http://ex/> .
@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .

ex:PersonShape a sh:NodeShape ;
    sh:targetClass ex:Person , ex:Human ;
    sh:severity sh:Warning ;
    sh:nodeKind sh:IRI ;
    sh:closed true ;
    sh:ignoredProperties ( <http://www.w3.org/1999/02/22-rdf-syntax-ns#type> ) ;
    sh:property [ sh:path ex:name ; sh:minCount 1 ; sh:datatype xsd:string ; sh:name "name" ;
                  sh:pattern "^a" ; sh:flags "i" ; rdfs:comment "an annotation" ] ,
                [ sh:path ex:status ; sh:in ( "active" ex:Retired ) ] ,
                [ sh:path ex:age ; sh:minInclusive 0 ; sh:or ( [ sh:datatype xsd:integer ] ) ] ,
                [ sh:path [ sh:inversePath ex:knows ] ; sh:minCount 1 ] ,
                [ sh:path ex:off ; sh:minCount 1 ; sh:deactivated true ] .

ex:NodeTargetShape a sh:NodeShape ; sh:targetNode ex:p1 ; sh:nodeKind sh:IRI .
"""


@pytest.fixture(scope="module")
def parsed():
    return specs_from_graph(Graph().parse(data=SHAPES, format="turtle"))


def test_specs_from_graph(parsed):
    specs, _ = parsed
    assert [(s.shape, s.target_class) for s in specs] == [("http://ex/PersonShape", EX + "Human"),
                                                           ("http://ex/PersonShape", EX + "Person")]
    spec = specs[1]
    assert (spec.source, spec.severity, spec.closed, spec.ignored_properties) == \
        ("found", "Warning", True, [RDF_TYPE])
    by_path = {p.path: p for p in spec.properties}
    assert [x.component for x in by_path[None].constraints] == ["nodeKind"]
    name = by_path[EX + "name"]
    assert sorted(x.component for x in name.constraints) == ["datatype", "minCount", "pattern"]
    pattern = next(x for x in name.constraints if x.component == "pattern")
    assert pattern.parameter == ("^a", re.IGNORECASE)
    status = by_path[EX + "status"].constraints[0]
    assert status.parameter == {term_key(lit("active")), term_key(iri(EX + "Retired"))}
    assert EX + "off" not in by_path                                         # deactivated


def test_not_checked_is_reported(parsed):
    _, not_checked = parsed
    reasons = {(n["shape"], n["component"]) for n in not_checked}
    assert ("http://ex/PersonShape", "or") in reasons                       # unsupported component
    assert ("http://ex/PersonShape", "path") in reasons                     # inverse path
    assert ("http://ex/NodeTargetShape", "target") in reasons               # only targetClass supported


def test_broken_list_is_not_checked():
    ttl = """
    @prefix sh: <http://www.w3.org/ns/shacl#> .
    @prefix rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .
    <http://ex/S> a sh:NodeShape ; sh:targetClass <http://ex/C> ;
        sh:property [ sh:path <http://ex/p> ; sh:in _:l1 ] .
    _:l1 rdf:first "a" ; rdf:rest _:l2 .
    """
    specs, not_checked = specs_from_graph(Graph().parse(data=ttl, format="turtle"))
    assert not_checked[0]["component"] == "in"
    assert "two levels" in not_checked[0]["reason"]


def test_to_term_round_trip():
    assert to_term(Literal("x", lang="en")) == lit("x", lang="en")
    assert to_term(Literal(5)) == lit("5", XSD + "integer")


def test_parse_order_is_stable():
    orders = set()
    for _ in range(5):
        specs, _ = specs_from_graph(Graph().parse(data=SHAPES, format="turtle"))
        orders.add(tuple(p.path for p in specs[1].properties))
    assert orders == {(None, EX + "age", EX + "name", EX + "status")}

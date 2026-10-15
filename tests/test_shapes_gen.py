import json

import pytest
from rdflib import Graph, Literal, URIRef
from rdflib.collection import Collection
from rdflib.namespace import RDF, SH, XSD

from baqueano.generate import shapes, thresholds as th
from baqueano.model import PropertyProfile, discovery_from_dict, discovery_to_dict
from baqueano.profiling import RDF_LANGSTRING, XSD_STRING
from tests.sample_discovery import PERSON, PLACE, S, XSD_DATE, sample_discovery


def pp(**kwargs):
    base = dict(path="http://ex/p", support=1.0, max_values_per_subject=1, iri_objects=0, literal_objects=0)
    return PropertyProfile(**{**base, **kwargs})


# -- decisions (pure) ----------------------------------------------------------

def test_property_left_out_below_min_support():
    assert shapes.constraints_for(pp(support=0.0499, literal_objects=1)) is None
    assert shapes.constraints_for(pp(support=th.PROPERTY_MIN_SUPPORT, literal_objects=1)) is not None


def test_min_count_threshold():
    assert shapes.constraints_for(pp(support=0.95, literal_objects=1)).min_count is True
    assert shapes.constraints_for(pp(support=0.9499, literal_objects=1)).min_count is False


def test_max_count_only_when_never_repeated():
    assert shapes.constraints_for(pp(max_values_per_subject=1, literal_objects=1)).max_count is True
    assert shapes.constraints_for(pp(max_values_per_subject=2, literal_objects=2)).max_count is False


def test_datatype_threshold():
    c = shapes.constraints_for(pp(literal_objects=100, datatypes={XSD_DATE: 95, XSD_STRING: 5}))
    assert (c.datatype, c.node_kind) == (XSD_DATE, None)
    c = shapes.constraints_for(pp(literal_objects=100, datatypes={XSD_DATE: 94, XSD_STRING: 6}))
    assert (c.datatype, c.node_kind) == (None, SH.Literal)


def test_no_datatype_when_objects_are_mostly_iris():
    c = shapes.constraints_for(pp(iri_objects=10, literal_objects=10, datatypes={XSD_STRING: 10}))
    assert (c.datatype, c.sh_class, c.node_kind) == (None, None, SH.IRIOrLiteral)


def test_class_threshold_uses_checked_objects():
    c = shapes.constraints_for(pp(iri_objects=500, target_classes={PLACE: 19}, objects_checked=20))
    assert (c.sh_class, c.node_kind) == (PLACE, None)
    c = shapes.constraints_for(pp(iri_objects=500, target_classes={PLACE: 18}, objects_checked=20))
    assert (c.sh_class, c.node_kind) == (None, SH.IRI)
    c = shapes.constraints_for(pp(iri_objects=5, objects_checked=0))
    assert (c.sh_class, c.node_kind) == (None, SH.IRI)


@pytest.mark.parametrize("kinds, expected", [
    (dict(bnode_objects=3), SH.BlankNode),
    (dict(iri_objects=1, bnode_objects=1), SH.BlankNodeOrIRI),
    (dict(literal_objects=1, bnode_objects=1, datatypes={XSD_STRING: 1}), SH.BlankNodeOrLiteral),
    (dict(iri_objects=1, literal_objects=1, bnode_objects=1, datatypes={XSD_STRING: 1}), None),
])
def test_node_kinds(kinds, expected):
    assert shapes.constraints_for(pp(**kinds)).node_kind == expected


def test_languages_most_used_first():
    c = shapes.constraints_for(pp(literal_objects=6, datatypes={RDF_LANGSTRING: 6},
                                  languages={"es": 1, "en": 4, "de": 1}))
    assert c.languages == ["en", "de", "es"]


# -- rendered Turtle -----------------------------------------------------------

@pytest.fixture(scope="module")
def graph():
    text = shapes.render(sample_discovery())
    assert text.startswith("# Draft SHACL shapes")
    return Graph().parse(data=text, format="turtle")


def prop_shape(g, shape, path):
    for node in g.objects(shape, SH.property):
        if (node, SH.path, URIRef(path)) in g:
            return node
    return None


PERSON_SHAPE = URIRef("urn:baqueano:shape:Person")


def test_node_shape(graph):
    from baqueano.generate.shapes import BAQ
    assert (PERSON_SHAPE, RDF.type, SH.NodeShape) in graph
    assert (PERSON_SHAPE, SH.targetClass, URIRef(PERSON)) in graph
    assert graph.value(PERSON_SHAPE, BAQ.sampleSize).toPython() == 200
    assert str(graph.value(PERSON_SHAPE, BAQ.sampleMethod)) == "first-n"
    place_shape = URIRef("urn:baqueano:shape:Place")
    assert graph.value(place_shape, BAQ.truncated).toPython() is True


def test_property_shapes(graph):
    name = prop_shape(graph, PERSON_SHAPE, S + "name")
    assert graph.value(name, SH.datatype) == XSD.string
    assert graph.value(name, SH.minCount).toPython() == 1
    assert graph.value(name, SH.maxCount).toPython() == 1
    assert graph.value(name, SH.severity) == SH.Info

    birth_place = prop_shape(graph, PERSON_SHAPE, S + "birthPlace")
    assert graph.value(birth_place, SH["class"]) == URIRef(PLACE)

    knows = prop_shape(graph, PERSON_SHAPE, S + "knows")
    assert graph.value(knows, SH["class"]) is None
    assert graph.value(knows, SH.nodeKind) == SH.IRI
    assert graph.value(knows, SH.minCount) is None
    assert graph.value(knows, SH.maxCount) is None

    nick = prop_shape(graph, PERSON_SHAPE, S + "nick")
    langs = Collection(graph, graph.value(nick, SH.languageIn))
    assert [str(x) for x in langs] == ["en", "es"]

    assert graph.value(prop_shape(graph, PERSON_SHAPE, S + "homepage"), SH.nodeKind) == SH.IRIOrLiteral


def test_left_out_properties(graph):
    assert prop_shape(graph, PERSON_SHAPE, S + "faxNumber") is None
    assert prop_shape(graph, PERSON_SHAPE, str(RDF.type)) is None


def test_every_property_shape_has_severity_and_support(graph):
    from baqueano.generate.shapes import BAQ
    nodes = list(graph.objects(None, SH.property))
    assert len(nodes) == 7 + 2   # Person: 7 kept; Place: label, containedInPlace
    for node in nodes:
        assert graph.value(node, SH.severity) == SH.Info
        assert graph.value(node, BAQ.support).datatype == XSD.decimal
    assert graph.value(prop_shape(graph, PERSON_SHAPE, S + "birthDate"), BAQ.support) == \
        Literal("0.97", datatype=XSD.decimal)


def test_shape_names_are_unique():
    from baqueano.model import ClassProfile
    names = shapes.shape_names([ClassProfile("http://a/Person", 1, "first-n", False, None),
                                ClassProfile("http://b/Person", 1, "first-n", False, None)])
    assert list(names.values()) == ["urn:baqueano:shape:Person", "urn:baqueano:shape:Person_2"]


def test_reads_only_what_discovery_json_holds():
    d = sample_discovery()
    reloaded = discovery_from_dict(json.loads(json.dumps(discovery_to_dict(d))))
    assert shapes.render(reloaded) == shapes.render(d)

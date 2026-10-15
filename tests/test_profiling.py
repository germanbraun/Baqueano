"""Profile computations on a hand-made sample whose numbers are easy to check.

Sample of 4 people:
    p1: type Person; name "Ana"@es, "Ana"@en; birthDate (xsd:date);
        knows p2, p3; worksFor org1
    p2: type Person; name "Luis" (duplicated row); birthDate; knows p1
    p3: type Person; name "Eva"; email "e@x"; knows _:b1
    p4: type Person (nothing else)
"""

import pytest

from baqueano import profiling
from baqueano.profiling import RDF_LANGSTRING, RDF_TYPE, XSD_STRING
from baqueano.steps.links import links_from_profiles
from tests.fakes import bnode, iri, lit

EX = "http://ex/"
PERSON, ORG = EX + "Person", EX + "Org"
NAME, BIRTH, KNOWS, WORKS, EMAIL = (EX + p for p in ("name", "birthDate", "knows", "worksFor", "email"))
XSD_DATE = "http://www.w3.org/2001/XMLSchema#date"
SUBJECTS = [EX + "p1", EX + "p2", EX + "p3", EX + "p4"]


def t(s, p, o):
    return {"s": iri(EX + s), "p": iri(p), "o": o}


ROWS = [
    t("p1", RDF_TYPE, iri(PERSON)),
    t("p1", NAME, lit("Ana", lang="es")),
    t("p1", NAME, lit("Ana", lang="en")),
    t("p1", BIRTH, lit("1990-01-01", XSD_DATE)),
    t("p1", KNOWS, iri(EX + "p2")),
    t("p1", KNOWS, iri(EX + "p3")),
    t("p1", WORKS, iri(EX + "org1")),
    t("p2", RDF_TYPE, iri(PERSON)),
    t("p2", NAME, lit("Luis")),
    t("p2", NAME, lit("Luis")),                      # same triple twice (e.g. in two graphs)
    t("p2", BIRTH, lit("1985-05-05", XSD_DATE)),
    t("p2", KNOWS, iri(EX + "p1")),
    t("p3", RDF_TYPE, iri(PERSON)),
    t("p3", NAME, lit("Eva")),
    t("p3", EMAIL, lit("e@x")),
    t("p3", KNOWS, bnode("b1")),
    t("p4", RDF_TYPE, iri(PERSON)),
    t("p9", NAME, lit("not in sample")),             # ignored: subject not profiled
]
TYPES = {EX + "p1": {PERSON}, EX + "p2": {PERSON}, EX + "p3": {PERSON}, EX + "org1": {ORG}}


@pytest.fixture
def profile():
    triples = profiling.triples_from_rows(ROWS)
    checked = profiling.objects_to_check(triples)
    return profiling.build_profile(PERSON, SUBJECTS, triples, checked, TYPES)


def prop(profile, path):
    return next(pp for pp in profile.properties if pp.path == path)


def test_triples_are_deduplicated():
    assert len(profiling.triples_from_rows(ROWS)) == len(ROWS) - 1


def test_sample_metadata(profile):
    assert profile.sample_size == 4
    assert profile.sample_method == "first-n"
    assert profile.truncated is False
    assert profile.example_instance == EX + "p1"   # most distinct properties


def test_properties_sorted_by_support(profile):
    assert [pp.path for pp in profile.properties] == [RDF_TYPE, KNOWS, NAME, BIRTH, EMAIL, WORKS]


def test_support(profile):
    assert prop(profile, RDF_TYPE).support == 1.0
    assert prop(profile, NAME).support == 0.75
    assert prop(profile, BIRTH).support == 0.5
    assert prop(profile, EMAIL).support == 0.25


def test_cardinality(profile):
    assert prop(profile, NAME).max_values_per_subject == 2    # p1 has two names
    assert prop(profile, KNOWS).max_values_per_subject == 2
    assert prop(profile, BIRTH).max_values_per_subject == 1   # duplicate row did not count twice


def test_object_kinds(profile):
    knows = prop(profile, KNOWS)
    assert (knows.iri_objects, knows.literal_objects, knows.bnode_objects) == (3, 0, 1)
    name = prop(profile, NAME)
    assert (name.iri_objects, name.literal_objects, name.bnode_objects) == (0, 4, 0)


def test_datatypes_and_languages(profile):
    name = prop(profile, NAME)
    assert name.datatypes == {RDF_LANGSTRING: 2, XSD_STRING: 2}
    assert name.languages == {"es": 1, "en": 1}
    assert prop(profile, BIRTH).datatypes == {XSD_DATE: 2}
    assert prop(profile, BIRTH).languages == {}


def test_target_classes(profile):
    knows = prop(profile, KNOWS)
    assert knows.objects_checked == 3          # p2, p3, p1 (the blank node is not checked)
    assert knows.target_classes == {PERSON: 3}
    assert prop(profile, WORKS).target_classes == {ORG: 1}
    assert prop(profile, RDF_TYPE).objects_checked == 0   # class objects are not type-checked


def test_objects_to_check_caps_per_property():
    rows = [t("p1", KNOWS, iri(f"{EX}o{i}")) for i in range(30)] + [t("p2", KNOWS, iri(EX + "o0"))]
    checked = profiling.objects_to_check(profiling.triples_from_rows(rows), per_property=5)
    assert checked == {KNOWS: [f"{EX}o{i}" for i in range(5)]}


def test_untyped_objects_lower_the_share():
    triples = profiling.triples_from_rows([t("p1", KNOWS, iri(EX + "p2")), t("p2", KNOWS, iri(EX + "x"))])
    checked = profiling.objects_to_check(triples)
    prof = profiling.build_profile(PERSON, [EX + "p1", EX + "p2"], triples, checked, {EX + "p2": {PERSON}})
    knows = prop(prof, KNOWS)
    assert knows.objects_checked == 2
    assert knows.target_classes == {PERSON: 1}


def test_links(profile):
    links = links_from_profiles([profile])
    assert [(link.path, link.target_class, link.support) for link in links] == [
        (KNOWS, PERSON, 0.75),
        (WORKS, ORG, 0.25),
    ]


def test_link_support_is_split_between_target_classes():
    triples = profiling.triples_from_rows([t("p1", KNOWS, iri(EX + "a")), t("p2", KNOWS, iri(EX + "b"))])
    checked = profiling.objects_to_check(triples)
    prof = profiling.build_profile(PERSON, [EX + "p1", EX + "p2"], triples, checked,
                                   {EX + "a": {PERSON}, EX + "b": {ORG}})
    assert sorted((link.target_class, link.support) for link in links_from_profiles([prof])) == \
        [(ORG, 0.5), (PERSON, 0.5)]


def test_empty_sample():
    prof = profiling.build_profile(PERSON, [], [], {}, {})
    assert prof.sample_size == 0
    assert prof.properties == []
    assert prof.example_instance is None


def test_detect_label_properties(profile):
    rdfs_label = "http://www.w3.org/2000/01/rdf-schema#label"
    schema_name = "https://schema.org/name"
    other = profiling.build_profile(ORG, [EX + "o"],
                                    profiling.triples_from_rows([
                                        {"s": iri(EX + "o"), "p": iri(schema_name), "o": lit("x")},
                                        {"s": iri(EX + "o"), "p": iri(rdfs_label), "o": lit("x")},
                                    ]), {}, {})
    assert profiling.detect_label_properties([profile, other]) == [rdfs_label, schema_name]

"""A small but realistic Discovery for generator tests.

Person (sample of 200) is built so that each shape rule has a clear answer:
    name        support 1.00, one xsd:string each          -> minCount, maxCount, datatype
    birthDate   support 0.97, xsd:date                     -> minCount, maxCount, datatype
    birthPlace  support 0.97, 20/20 checked are Place      -> sh:class Place
    knows       support 0.60, 18/20 checked are Person     -> 0.90 < 0.95: nodeKind IRI
    nick        support 0.50, @en/@es                      -> datatype langString, languageIn
    homepage    support 0.30, IRIs and literals            -> nodeKind IRIOrLiteral
    email       support 0.41, two values for someone       -> no minCount, no maxCount
    fax         support 0.02                               -> left out
"""

from baqueano.model import ClassInfo, ClassProfile, Discovery, PropertyProfile, StepResult
from baqueano.profiling import RDF_LANGSTRING, RDF_TYPE, XSD_STRING
from baqueano.steps.links import links_from_profiles

S = "https://schema.org/"
RDFS_LABEL = "http://www.w3.org/2000/01/rdf-schema#label"
XSD_DATE = "http://www.w3.org/2001/XMLSchema#date"
PERSON, PLACE, ORG = S + "Person", S + "Place", "http://unknown.org/vocab/Organisation"


def person_profile() -> ClassProfile:
    props = [
        PropertyProfile(RDF_TYPE, 1.0, 1, 200, 0),
        PropertyProfile(S + "name", 1.0, 1, 0, 200, datatypes={XSD_STRING: 200}),
        PropertyProfile(S + "birthDate", 0.97, 1, 0, 194, datatypes={XSD_DATE: 194}),
        PropertyProfile(S + "birthPlace", 0.97, 1, 194, 0, target_classes={PLACE: 20}, objects_checked=20),
        PropertyProfile(S + "knows", 0.6, 3, 300, 0, target_classes={PERSON: 18}, objects_checked=20),
        PropertyProfile(S + "nick", 0.5, 2, 0, 150, datatypes={RDF_LANGSTRING: 150},
                        languages={"en": 100, "es": 50}),
        PropertyProfile(S + "email", 0.41, 2, 0, 90, datatypes={XSD_STRING: 90}),
        PropertyProfile(S + "homepage", 0.3, 1, 40, 20, datatypes={XSD_STRING: 20}),
        PropertyProfile(S + "faxNumber", 0.02, 1, 0, 4, datatypes={XSD_STRING: 4}),
    ]
    return ClassProfile(PERSON, 200, "first-n", False, "http://ex/person/1", props)


def place_profile() -> ClassProfile:
    props = [
        PropertyProfile(RDF_TYPE, 1.0, 1, 50, 0),
        PropertyProfile(RDFS_LABEL, 1.0, 1, 0, 50, datatypes={XSD_STRING: 50}),
        PropertyProfile(S + "containedInPlace", 0.8, 1, 40, 0, target_classes={PLACE: 10}, objects_checked=10),
    ]
    return ClassProfile(PLACE, 50, "first-n", True, "http://ex/place/1", props)


def sample_discovery(graph_scope: str | None = None) -> Discovery:
    profiles = [person_profile(), place_profile()]
    return Discovery(
        endpoint="http://example.org/sparql",
        started_at="2026-10-15T12:00:00+00:00",
        graph_scope=graph_scope,
        steps=[StepResult("probe", "ok", "endpoint answers")],
        graphs=["http://ex/graph/people"] if graph_scope is None else [graph_scope],
        triple_count=5000,
        triple_count_exact=True,
        classes=[ClassInfo(PERSON, 200, True, label="Person"), ClassInfo(PLACE, 50, False),
                 ClassInfo(ORG, None, False)],
        label_properties=[RDFS_LABEL, S + "name"],
        profiles=profiles,
        links=links_from_profiles(profiles),
    )

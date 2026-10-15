import pytest

from baqueano.generate.names import identifier, slug, unique, unique_map, variable
from baqueano.generate.prefixes import PrefixWriter


@pytest.mark.parametrize("iri, expected", [
    ("https://schema.org/Person", "person"),
    ("https://schema.org/PostalAddress", "postal-address"),
    ("http://www.wikidata.org/entity/Q5", "q5"),
    ("http://ex/has_part.v2", "has-part-v2"),
    ("http://ex/", "http-ex"),           # no local name: the whole IRI is used
])
def test_slug(iri, expected):
    assert slug(iri) == expected


def test_variable_and_identifier():
    assert variable("https://schema.org/Person") == "person"
    assert variable("https://schema.org/birthDate") == "birthDate"
    assert variable("http://www.wikidata.org/prop/direct/P31") == "p31"
    assert identifier("http://ex/foo-bar.baz") == "foo_bar_baz"


def test_unique():
    assert unique(["a", "b", "a", "a"]) == ["a", "b", "a-2", "a-3"]
    assert unique(["a", "a-2", "a"]) == ["a", "a-2", "a-3"]       # avoids existing names
    assert unique(["x", "x"], separator="") == ["x", "x2"]
    assert unique_map(["http://a/P", "http://b/P", "http://a/P"], slug) == {"http://a/P": "p", "http://b/P": "p-2"}


def test_prefix_writer():
    pw = PrefixWriter()
    assert pw.iri("https://schema.org/Person") == "schema:Person"
    assert pw.iri("http://unknown.org/x") == "<http://unknown.org/x>"
    assert pw.iri("http://www.w3.org/2000/01/rdf-schema#label") == "rdfs:label"
    assert pw.declarations() == ("PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>\n"
                                 "PREFIX schema: <https://schema.org/>\n")

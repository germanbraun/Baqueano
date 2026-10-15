import pytest

from baqueano import vocabularies as v
from baqueano.model import ClassInfo, ClassProfile, PropertyProfile
from baqueano.steps.namespaces import vocabularies_from
from tests.helpers import make_ctx


@pytest.mark.parametrize("iri, expected", [
    ("https://schema.org/Person", ("https://schema.org/", "Person")),
    ("http://www.w3.org/2000/01/rdf-schema#label", ("http://www.w3.org/2000/01/rdf-schema#", "label")),
    ("http://www.wikidata.org/prop/direct/P31", ("http://www.wikidata.org/prop/direct/", "P31")),
    ("http://ex/ns/", ("http://ex/ns/", "")),
    ("urn:isbn:123", ("urn:isbn:123", "")),
])
def test_split_iri(iri, expected):
    assert v.split_iri(iri) == expected


def test_shorten():
    assert v.shorten("https://schema.org/Person") == "schema:Person"
    assert v.shorten("http://www.wikidata.org/prop/direct/P31") == "wdt:P31"
    assert v.shorten("http://unknown.org/x/Thing") == "<http://unknown.org/x/Thing>"
    assert v.shorten("https://schema.org/has(paren)") == "<https://schema.org/has(paren)>"


def test_prefixes_are_unique():
    prefixes = [prefix for prefix, _ in v.KNOWN.values()]
    assert len(prefixes) == len(set(prefixes))


def test_is_safe_iri():
    assert v.is_safe_iri("http://ex/a")
    assert not v.is_safe_iri("http://ex/a b")
    assert not v.is_safe_iri("http://ex/<a>")
    assert not v.is_safe_iri("")


def test_vocabularies_from_discovery():
    d = make_ctx(void={"vocabularies": ["http://xmlns.com/foaf/0.1/", "https://schema.org/"]}).discovery
    d.classes = [ClassInfo("https://schema.org/Person", 3, True), ClassInfo("http://ex/Thing", 1, True)]
    d.profiles = [ClassProfile("https://schema.org/Person", 3, "first-n", False, None, [
        PropertyProfile("https://schema.org/name", 1.0, 1, 0, 3),
        PropertyProfile("https://schema.org/knows", 0.5, 1, 2, 0, target_classes={"http://ex/Thing": 2}),
    ])]
    result = {x["namespace"]: x for x in vocabularies_from(d)}
    assert result["https://schema.org/"] == {"namespace": "https://schema.org/", "prefix": "schema",
                                             "name": "schema.org", "terms": 3, "declared_in_void": True}
    assert result["http://ex/"]["terms"] == 1
    assert result["http://ex/"]["prefix"] is None
    assert result["http://xmlns.com/foaf/0.1/"]["terms"] == 0     # declared in VoID only
    assert list(result)[0] == "https://schema.org/"               # most used first

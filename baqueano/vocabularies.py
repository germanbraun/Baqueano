"""Table of known vocabularies, and IRI helpers (pure, no I/O).

No prefix.cc lookup in v0: only what is listed here gets a known prefix.
"""

from __future__ import annotations

# namespace -> (prefix, name). Prefixes are unique.
KNOWN: dict[str, tuple[str, str]] = {
    "http://www.w3.org/1999/02/22-rdf-syntax-ns#": ("rdf", "RDF"),
    "http://www.w3.org/2000/01/rdf-schema#": ("rdfs", "RDF Schema"),
    "http://www.w3.org/2002/07/owl#": ("owl", "OWL"),
    "http://www.w3.org/2001/XMLSchema#": ("xsd", "XML Schema datatypes"),
    "http://www.w3.org/2004/02/skos/core#": ("skos", "SKOS"),
    "http://www.w3.org/2008/05/skos-xl#": ("skosxl", "SKOS-XL"),
    "https://schema.org/": ("schema", "schema.org"),
    "http://schema.org/": ("sdo", "schema.org (http)"),
    "http://xmlns.com/foaf/0.1/": ("foaf", "FOAF"),
    "http://purl.org/dc/elements/1.1/": ("dc", "Dublin Core elements"),
    "http://purl.org/dc/terms/": ("dct", "Dublin Core terms"),
    "http://purl.org/dc/dcmitype/": ("dcmitype", "DCMI types"),
    "http://www.w3.org/ns/prov#": ("prov", "PROV-O"),
    "http://www.opengis.net/ont/geosparql#": ("geo", "GeoSPARQL"),
    "http://www.opengis.net/def/function/geosparql/": ("geof", "GeoSPARQL functions"),
    "http://www.w3.org/2003/01/geo/wgs84_pos#": ("wgs84", "WGS84 Geo Positioning"),
    "http://www.w3.org/2006/time#": ("time", "OWL-Time"),
    "http://www.w3.org/ns/dcat#": ("dcat", "DCAT"),
    "http://www.w3.org/ns/org#": ("org", "Organization ontology"),
    "http://www.w3.org/2006/vcard/ns#": ("vcard", "vCard"),
    "http://www.w3.org/ns/shacl#": ("sh", "SHACL"),
    "http://rdfs.org/ns/void#": ("void", "VoID"),
    "http://www.w3.org/ns/sparql-service-description#": ("sd", "SPARQL Service Description"),
    "http://www.w3.org/ns/ldp#": ("ldp", "LDP"),
    "http://www.w3.org/ns/oa#": ("oa", "Web Annotation"),
    "http://rdfs.org/sioc/ns#": ("sioc", "SIOC"),
    "http://purl.org/ontology/bibo/": ("bibo", "BIBO"),
    "http://www.geonames.org/ontology#": ("gn", "GeoNames"),
    "http://qudt.org/schema/qudt/": ("qudt", "QUDT"),
    "http://www.wikidata.org/entity/": ("wd", "Wikidata entities"),
    "http://www.wikidata.org/prop/direct/": ("wdt", "Wikidata direct properties"),
    "http://www.wikidata.org/prop/": ("p", "Wikidata properties"),
    "http://www.wikidata.org/prop/statement/": ("ps", "Wikidata statements"),
    "http://www.wikidata.org/prop/qualifier/": ("pq", "Wikidata qualifiers"),
    "http://wikiba.se/ontology#": ("wikibase", "Wikibase"),
    "http://dbpedia.org/ontology/": ("dbo", "DBpedia ontology"),
    "http://dbpedia.org/property/": ("dbp", "DBpedia properties"),
    "http://dbpedia.org/resource/": ("dbr", "DBpedia resources"),
    "http://purl.uniprot.org/core/": ("up", "UniProt core"),
    "http://purl.obolibrary.org/obo/": ("obo", "OBO"),
    "http://biohackathon.org/resource/faldo#": ("faldo", "FALDO"),
}

PREFIXES: dict[str, str] = {prefix: ns for ns, (prefix, _) in KNOWN.items()}

# Namespaces whose classes describe the data rather than being data.
METADATA_NAMESPACES = {
    "http://www.w3.org/1999/02/22-rdf-syntax-ns#",
    "http://www.w3.org/2000/01/rdf-schema#",
    "http://www.w3.org/2002/07/owl#",
    "http://www.w3.org/ns/shacl#",
    "http://rdfs.org/ns/void#",
    "http://www.w3.org/ns/sparql-service-description#",
}


RDF_TYPE = "http://www.w3.org/1999/02/22-rdf-syntax-ns#type"

# Classes that are mostly plumbing: numerous, but rarely what a user queries.
# Profiled only after the other classes (never skipped). Each entry comes
# from a real run; extend it when a new endpoint shows the same pattern.
INFRASTRUCTURE_NAMESPACES = {
    "http://wikiba.se/ontology#",                    # Wikidata statements, ranks, value nodes
    "http://www.wikidata.org/prop/novalue/",         # Wikidata "no value" markers
    "http://biohackathon.org/resource/faldo#",       # UniProt sequence positions and regions
}
INFRASTRUCTURE_CLASSES = {
    "http://dbpedia.org/ontology/Image",              # DBpedia: one node per image file
    "http://dbpedia.org/ontology/CareerStation",      # DBpedia: reified career entries
    "http://xmlns.com/foaf/0.1/Document",             # DBpedia: Wikipedia page records
}


def is_infrastructure(iri: str) -> bool:
    return iri in INFRASTRUCTURE_CLASSES or namespace(iri) in INFRASTRUCTURE_NAMESPACES


def expand(text: str) -> str | None:
    """'wd:Q5' -> full IRI with a known prefix; a full IRI (or <IRI>) as is; None if unknown."""
    text = text.strip()
    if text.startswith("<") and text.endswith(">"):
        text = text[1:-1]
    if "://" in text or text.startswith("urn:"):
        return text if is_safe_iri(text) else None
    prefix, sep, local = text.partition(":")
    if sep and prefix in PREFIXES:
        iri = PREFIXES[prefix] + local
        return iri if is_safe_iri(iri) else None
    return None


def split_iri(iri: str) -> tuple[str, str]:
    """Split at the last '#' or '/': ('https://schema.org/', 'Person')."""
    cut = max(iri.rfind("#"), iri.rfind("/"))
    if cut < 0 or cut == len(iri) - 1:
        return iri, ""
    return iri[: cut + 1], iri[cut + 1:]


def namespace(iri: str) -> str:
    return split_iri(iri)[0]


def local_name(iri: str) -> str:
    """Local part of an IRI, or the IRI itself if it has none."""
    return split_iri(iri)[1] or iri


def known_prefix(ns: str) -> str | None:
    entry = KNOWN.get(ns)
    return entry[0] if entry else None


def shorten(iri: str) -> str:
    """'schema:Person' when the namespace is known, else '<full IRI>'."""
    ns, local = split_iri(iri)
    prefix = known_prefix(ns)
    if prefix and local and is_valid_local(local):
        return f"{prefix}:{local}"
    return f"<{iri}>"


IRIREF_FORBIDDEN = set('<>"{}|^`\\')


def is_safe_iri(iri: str) -> bool:
    """True if `iri` can be written as <iri> in a SPARQL query (SPARQL IRIREF rule)."""
    return bool(iri) and not any(c in IRIREF_FORBIDDEN or ord(c) <= 0x20 for c in iri)


def is_valid_local(local: str) -> bool:
    """Conservative check that `local` can be written as prefix:local in SPARQL/Turtle."""
    if not local or local[0] in ".-" or local[-1] == ".":
        return False
    return all(c.isalnum() or c in "_-." for c in local)

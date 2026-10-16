"""Per-class profile computations (pure: rows in, ClassProfile out).

Definitions, for one class and its sample of subjects S (|S| = sample_size):

    support(p)                 |{s in S having p}| / |S|
    max_values_per_subject(p)  largest number of distinct values of p on one s
    iri/literal/bnode_objects  distinct (s, p, o) triples by object kind
    datatypes(p)               literal values per datatype; untagged plain
                               literals count as xsd:string, tagged as rdf:langString
    languages(p)               literal values per language tag
    target_classes(p)          among the IRI objects that were type-checked
                               (objects_checked, at most OBJECTS_PER_PROPERTY),
                               how many have each rdf:type
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field

from baqueano.model import ClassProfile, PropertyProfile

RDF_TYPE = "http://www.w3.org/1999/02/22-rdf-syntax-ns#type"
XSD_STRING = "http://www.w3.org/2001/XMLSchema#string"
RDF_LANGSTRING = "http://www.w3.org/1999/02/22-rdf-syntax-ns#langString"

OBJECTS_PER_PROPERTY = 20      # IRI objects type-checked per property
SAMPLE_METHOD = "first-n"

# Label properties, in order of preference for the generated queries.
LABEL_PROPERTIES = [
    "http://www.w3.org/2000/01/rdf-schema#label",
    "http://www.w3.org/2004/02/skos/core#prefLabel",
    "https://schema.org/name",
    "http://schema.org/name",
    "http://purl.org/dc/terms/title",
    "http://xmlns.com/foaf/0.1/name",
]

Triple = tuple[str, str, dict]   # (subject IRI, property IRI, object term)


@dataclass
class Sample:
    """The raw sample behind a ClassProfile. Kept in memory for the validate
    step only; never written to discovery.json (it can be large)."""
    class_iri: str
    subjects: list[str]                      # profiled subjects (the focus nodes)
    triples: list[Triple]
    object_types: dict[str, set[str]] = field(default_factory=dict)
    checked: set[str] = field(default_factory=set)   # objects whose types were looked up
    truncated: bool = False


def term_key(term: dict) -> tuple:
    """Hashable identity of a simplified term."""
    return (term["type"], term["value"], term.get("datatype"), term.get("lang"))


def triples_from_rows(rows: list[dict]) -> list[Triple]:
    """?s ?p ?o rows -> distinct triples, first-seen order (the same triple can
    come back more than once, e.g. when it is stored in several graphs)."""
    seen, triples = set(), []
    for row in rows:
        s, p, o = row.get("s"), row.get("p"), row.get("o")
        if not s or not p or not o:
            continue
        key = (s["value"], p["value"], term_key(o))
        if key in seen:
            continue
        seen.add(key)
        triples.append((s["value"], p["value"], o))
    return triples


def objects_to_check(triples: list[Triple], per_property: int = OBJECTS_PER_PROPERTY) -> dict[str, list[str]]:
    """For each property, the first `per_property` distinct IRI objects to type-check.
    rdf:type is skipped: its objects are classes."""
    chosen: dict[str, list[str]] = {}
    for _, p, o in triples:
        if p == RDF_TYPE or o["type"] != "uri":
            continue
        objs = chosen.setdefault(p, [])
        if len(objs) < per_property and o["value"] not in objs:
            objs.append(o["value"])
    return chosen


def types_from_rows(rows: list[dict]) -> dict[str, set[str]]:
    """?o ?t rows -> {object: {types}}."""
    types: dict[str, set[str]] = {}
    for row in rows:
        o, t = row.get("o"), row.get("t")
        if o and t and t["type"] == "uri":
            types.setdefault(o["value"], set()).add(t["value"])
    return types


def literal_datatype(term: dict) -> str:
    if "datatype" in term:
        return term["datatype"]
    return RDF_LANGSTRING if "lang" in term else XSD_STRING


def build_profile(
    class_iri: str,
    subjects: list[str],
    triples: list[Triple],
    checked: dict[str, list[str]],
    object_types: dict[str, set[str]],
    truncated: bool = False,
    failed_batches: int = 0,
) -> ClassProfile:
    """Compute the ClassProfile of `class_iri` from its sample.

    subjects:     the sampled subjects that were actually profiled (denominator)
    triples:      distinct triples of those subjects
    checked:      property -> IRI objects whose types were looked up
    object_types: object -> its rdf:types (for the checked objects)
    """
    subject_set = set(subjects)
    values_per_subject: dict[str, Counter] = {}
    kinds: dict[str, Counter] = {}
    datatypes: dict[str, Counter] = {}
    languages: dict[str, Counter] = {}
    props_per_subject: dict[str, set[str]] = {}

    for s, p, o in triples:
        if s not in subject_set:
            continue
        values_per_subject.setdefault(p, Counter())[s] += 1
        kinds.setdefault(p, Counter())[o["type"]] += 1
        props_per_subject.setdefault(s, set()).add(p)
        if o["type"] == "literal":
            datatypes.setdefault(p, Counter())[literal_datatype(o)] += 1
            if "lang" in o:
                languages.setdefault(p, Counter())[o["lang"]] += 1

    properties = []
    for p, per_subject in values_per_subject.items():
        targets: Counter = Counter()
        for obj in checked.get(p, []):
            for t in object_types.get(obj, ()):
                targets[t] += 1
        properties.append(PropertyProfile(
            path=p,
            support=round(len(per_subject) / len(subjects), 4) if subjects else 0.0,
            max_values_per_subject=max(per_subject.values()),
            iri_objects=kinds[p]["uri"],
            literal_objects=kinds[p]["literal"],
            bnode_objects=kinds[p]["bnode"],
            datatypes=dict(datatypes.get(p, {})),
            languages=dict(languages.get(p, {})),
            target_classes=dict(targets.most_common()),
            objects_checked=len(checked.get(p, [])),
        ))
    properties.sort(key=lambda pp: (-pp.support, pp.path))

    return ClassProfile(
        class_iri=class_iri,
        sample_size=len(subjects),
        sample_method=SAMPLE_METHOD,
        truncated=truncated,
        example_instance=richest_subject(subjects, props_per_subject),
        properties=properties,
        failed_batches=failed_batches,
    )


def richest_subject(subjects: list[str], props_per_subject: dict[str, set[str]]) -> str | None:
    """The sampled subject with the most distinct properties (first one on ties)."""
    best, best_n = None, -1
    for s in subjects:
        n = len(props_per_subject.get(s, ()))
        if n > best_n:
            best, best_n = s, n
    return best


def detect_label_properties(profiles: list[ClassProfile]) -> list[str]:
    """Known label properties seen in any profile, in preference order."""
    seen = {pp.path for prof in profiles for pp in prof.properties}
    return [p for p in LABEL_PROPERTIES if p in seen]

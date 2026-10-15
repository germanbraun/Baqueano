"""Vocabularies in use, derived from every IRI discovered so far (no queries).

Runs last, so it sees property IRIs from the profile as well as classes.
Each namespace (IRI split at the last '#' or '/') is matched against the
known-vocabularies table. Vocabularies declared in VoID are listed too.

discovery.vocabularies: [{"namespace", "prefix", "name", "terms", "declared_in_void"}]
"""

from __future__ import annotations

from baqueano import model
from baqueano.context import Context
from baqueano.model import Discovery, StepResult
from baqueano.vocabularies import KNOWN, split_iri

NAME = "namespaces"


def terms_in_use(discovery: Discovery) -> set[str]:
    """Class and property IRIs seen anywhere in the discovery."""
    terms = {c.iri for c in discovery.classes}
    for prof in discovery.profiles:
        terms.add(prof.class_iri)
        for pp in prof.properties:
            terms.add(pp.path)
            terms.update(pp.target_classes)
    return terms


def vocabularies_from(discovery: Discovery) -> list[dict]:
    """Namespaces with their number of distinct terms, most used first (pure)."""
    by_namespace: dict[str, set[str]] = {}
    for term in terms_in_use(discovery):
        ns, local = split_iri(term)
        if local:
            by_namespace.setdefault(ns, set()).add(term)

    declared = set((discovery.void or {}).get("vocabularies", []))
    for ns in declared:
        by_namespace.setdefault(ns, set())

    vocabularies = []
    for ns, terms in by_namespace.items():
        prefix, name = KNOWN.get(ns, (None, None))
        vocabularies.append({"namespace": ns, "prefix": prefix, "name": name,
                             "terms": len(terms), "declared_in_void": ns in declared})
    vocabularies.sort(key=lambda v: (-v["terms"], v["namespace"]))
    return vocabularies


def run(client, ctx: Context) -> StepResult:
    ctx.discovery.vocabularies = vocabularies_from(ctx.discovery)
    known = sum(1 for v in ctx.discovery.vocabularies if v["prefix"])
    return StepResult(NAME, model.OK, f"{len(ctx.discovery.vocabularies)} namespace(s), {known} known")

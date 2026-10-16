"""Step 7: per-class profile, by sampling.

For each of the --max-classes most populated classes (metadata classes such
as owl:Class or sh:NodeShape are skipped):

    1. sample:  SELECT ?s WHERE { ?s a <C> } LIMIT N      (first N, not random)
    2. triples: VALUES ?s { ...50 subjects... } ?s ?p ?o, LIMIT per batch;
                hitting the limit marks the profile truncated
    3. types:   VALUES ?o { ... } ?o a ?t, for up to OBJECTS_PER_PROPERTY
                IRI objects per property
    4. compute: profiling.build_profile (pure)

Blank-node instances cannot be put in VALUES, so they are not profiled in v0.
A failed batch drops its subjects from the profile and is counted in
failed_batches. When the budget runs out, the remaining classes are skipped.
"""

from __future__ import annotations

import logging

from baqueano import model, profiling, scope
from baqueano.context import Context, step_status, worst
from baqueano.model import ClassInfo, ClassProfile, StepResult
from baqueano.vocabularies import METADATA_NAMESPACES, is_safe_iri, namespace, shorten

logger = logging.getLogger(__name__)

NAME = "profile"
SUBJECT_BATCH = 50
TRIPLES_LIMIT = 10000
TYPE_BATCH = 200
TYPES_LIMIT = 10000


def sample_query(class_iri: str, n: int, graph: str | None) -> str:
    return f"SELECT ?s WHERE {{ {scope.where(f'?s a <{class_iri}>', graph)} }} LIMIT {n}"


def triples_query(subjects: list[str], graph: str | None) -> str:
    values = " ".join(f"<{s}>" for s in subjects)
    return (f"SELECT ?s ?p ?o WHERE {{ VALUES ?s {{ {values} }} {scope.where('?s ?p ?o', graph)} }} "
            f"LIMIT {TRIPLES_LIMIT}")


def types_query(objects: list[str], graph: str | None) -> str:
    values = " ".join(f"<{o}>" for o in objects)
    return (f"SELECT ?o ?t WHERE {{ VALUES ?o {{ {values} }} {scope.where('?o a ?t', graph)} }} "
            f"LIMIT {TYPES_LIMIT}")


def step_label(class_iri: str, part: str) -> str:
    """Query label for queries.log, e.g. 'profile:schema:Person:sample'."""
    return f"profile:{shorten(class_iri)}:{part}"


def chunks(items: list, size: int) -> list[list]:
    return [items[i:i + size] for i in range(0, len(items), size)]


def classes_to_profile(classes: list[ClassInfo], max_classes: int) -> tuple[list[ClassInfo], int]:
    """The first max_classes profilable classes, and how many metadata classes were skipped."""
    chosen, metadata = [], 0
    for c in classes:
        if namespace(c.iri) in METADATA_NAMESPACES:
            metadata += 1
        elif c.count != 0 and is_safe_iri(c.iri):
            chosen.append(c)
    return chosen[:max_classes], metadata


def profile_class(client, class_iri: str, sample: int, graph: str | None) -> tuple[ClassProfile | None, str, str]:
    """Profile one class. Returns (profile or None, status, message)."""
    # 1. Sample of subjects.
    sampled = client.query(step_label(class_iri, "sample"), sample_query(class_iri, sample, graph))
    if sampled.status != "ok":
        return None, step_status(sampled.status), f"sample failed: {sampled.error}"
    subjects, bnodes = [], 0
    for row in sampled.rows:
        term = row.get("s")
        if not term:
            continue
        if term["type"] != "uri" or not is_safe_iri(term["value"]):
            bnodes += 1
        elif term["value"] not in subjects:
            subjects.append(term["value"])
    if not subjects:
        return None, model.UNSUPPORTED, f"no IRI instances to profile ({bnodes} blank node(s))"

    # 2. Triples of the sample, in batches.
    statuses = [model.OK]
    rows, profiled, truncated, failed = [], [], False, 0
    for batch in chunks(subjects, SUBJECT_BATCH):
        outcome = client.query(step_label(class_iri, "triples"), triples_query(batch, graph))
        if outcome.status != "ok":
            failed += 1
            statuses.append(step_status(outcome.status))
            if outcome.status == "budget_exhausted":
                break
            continue
        if len(outcome.rows) >= TRIPLES_LIMIT:
            logger.debug("%s: triples batch hit LIMIT %d, profile truncated", class_iri, TRIPLES_LIMIT)
            truncated = True
        rows.extend(outcome.rows)
        profiled.extend(batch)
    if not profiled:
        return None, worst(*statuses), f"all {failed} triples batch(es) failed"
    triples = profiling.triples_from_rows(rows)

    # 3. Types of a subsample of IRI objects.
    to_check = profiling.objects_to_check(triples)
    all_objects = list(dict.fromkeys(o for objs in to_check.values() for o in objs if is_safe_iri(o)))
    object_types, checked_ok = {}, set()
    for batch in chunks(all_objects, TYPE_BATCH):
        outcome = client.query(step_label(class_iri, "types"), types_query(batch, graph))
        if outcome.status != "ok":
            statuses.append(step_status(outcome.status))
            if outcome.status == "budget_exhausted":
                break
            continue
        object_types.update(profiling.types_from_rows(outcome.rows))
        checked_ok.update(batch)
    checked = {p: [o for o in objs if o in checked_ok] for p, objs in to_check.items()}

    # 4. Compute.
    prof = profiling.build_profile(class_iri, profiled, triples, checked, object_types,
                                   truncated=truncated, failed_batches=failed)
    notes = [f"{prof.sample_size} instances, {len(prof.properties)} properties"]
    if bnodes:
        notes.append(f"{bnodes} blank-node instance(s) not profiled")
    if truncated:
        notes.append("truncated")
    if failed:
        notes.append(f"{failed} batch(es) failed")
    return prof, worst(*statuses), ", ".join(notes)


def run(client, ctx: Context) -> StepResult:
    discovery = ctx.discovery
    settings = ctx.settings
    candidates, metadata = classes_to_profile(discovery.classes, settings.max_classes)
    if not candidates:
        return StepResult(NAME, model.OK, "no classes to profile")

    statuses = [model.OK]
    out_of_budget = False
    for i, cls in enumerate(candidates):
        prof, status, message = profile_class(client, cls.iri, settings.sample, settings.graph)
        logger.debug("profile %s: %s (%s)", cls.iri, status, message)
        if prof is not None:
            discovery.profiles.append(prof)
        # A class with only blank-node instances is a v0 limitation, not a degraded run.
        statuses.append(model.OK if status == model.UNSUPPORTED else status)
        if status == model.SKIPPED:
            logger.debug("budget exhausted after %d of %d classes", i, len(candidates))
            out_of_budget = True
            break

    discovery.label_properties = profiling.detect_label_properties(discovery.profiles)

    parts = [f"{len(discovery.profiles)} of {len(candidates)} classes profiled (sample ≤ {settings.sample})"]
    if metadata:
        parts.append(f"{metadata} metadata class(es) skipped")
    truncated = sum(p.truncated for p in discovery.profiles)
    if truncated:
        parts.append(f"{truncated} truncated")
    failed = sum(1 for s in statuses if s in (model.ERROR, model.TIMEOUT))
    if failed:
        parts.append(f"{failed} class(es) with failed queries")
    if out_of_budget:
        parts.append("budget ran out")
    return StepResult(NAME, worst(*statuses), "; ".join(parts))

"""Step 7: per-class profile, by sampling.

Which classes (classes_to_profile), at most --max-classes of them:
    1. the classes requested with --class, in the order given;
    2. then the others by instance count, skipping metadata classes
       (owl:Class, sh:NodeShape, ...) and moving known infrastructure classes
       (vocabularies.INFRASTRUCTURE_*) to the end.

How each class is sampled (sample_plan), N = --sample:
    all            exact count <= N: every instance (LIMIT N)
    random-offset  count known: SAMPLE_BLOCKS blocks of N/SAMPLE_BLOCKS
                   consecutive instances at random OFFSETs below
                   min(count, MAX_OFFSET); reproducible with --seed.
                   Blocks that fail are dropped; if all fail, first-n.
    first-n        count unknown: the first N the engine returns
Not truly random either way: OFFSET without ORDER BY follows engine order.
Except for "all", each query asks for OVERSAMPLE times the rows it needs and
keeps the first distinct instances.

Then, for the sampled subjects:
    triples: VALUES ?s { ...50 subjects... } ?s ?p ?o, LIMIT per batch;
             hitting the limit marks the profile truncated
    types:   VALUES ?o { ... } ?o <class property> ?t, for up to
             OBJECTS_PER_PROPERTY IRI objects per property
    compute: profiling.build_profile (pure)

Blank-node instances cannot be put in VALUES, so they are not profiled.
A failed batch drops its subjects from the profile and is counted in
failed_batches. When the budget runs out, the remaining classes are skipped.
"""

from __future__ import annotations

import logging
import random

from baqueano import model, profiling, scope
from baqueano.context import Context, Settings, step_status, worst
from baqueano.model import ClassInfo, ClassProfile, StepResult
from baqueano.vocabularies import METADATA_NAMESPACES, is_infrastructure, is_safe_iri, namespace, shorten

logger = logging.getLogger(__name__)

NAME = "profile"
SUBJECT_BATCH = 50
TRIPLES_LIMIT = 10000
TYPE_BATCH = 200
TYPES_LIMIT = 10000
SAMPLE_BLOCKS = 4
MAX_OFFSET = 1_000_000      # deep OFFSETs get slow on most engines
OVERSAMPLE = 2              # rows asked per wanted instance: engines repeat an instance
                            # typed in several graphs (DBpedia: ~half of each block)

ALL, RANDOM_OFFSET, FIRST_N = "all", "random-offset", "first-n"


# -- queries -------------------------------------------------------------------

def sample_query(class_iri: str, n: int, graph: str | None, class_property: str = profiling.RDF_TYPE,
                 offset: int = 0) -> str:
    pattern = scope.is_a("?s", f"<{class_iri}>", class_property)
    offset_text = f" OFFSET {offset}" if offset else ""
    return f"SELECT ?s WHERE {{ {scope.where(pattern, graph)} }}{offset_text} LIMIT {n}"


def triples_query(subjects: list[str], graph: str | None) -> str:
    values = " ".join(f"<{s}>" for s in subjects)
    return (f"SELECT ?s ?p ?o WHERE {{ VALUES ?s {{ {values} }} {scope.where('?s ?p ?o', graph)} }} "
            f"LIMIT {TRIPLES_LIMIT}")


def types_query(objects: list[str], graph: str | None, class_property: str = profiling.RDF_TYPE) -> str:
    values = " ".join(f"<{o}>" for o in objects)
    pattern = scope.is_a("?o", "?t", class_property)
    return (f"SELECT ?o ?t WHERE {{ VALUES ?o {{ {values} }} {scope.where(pattern, graph)} }} "
            f"LIMIT {TYPES_LIMIT}")


def step_label(class_iri: str, part: str) -> str:
    """Query label for queries.log, e.g. 'profile:schema:Person:sample'."""
    return f"profile:{shorten(class_iri)}:{part}"


def chunks(items: list, size: int) -> list[list]:
    return [items[i:i + size] for i in range(0, len(items), size)]


# -- decisions (pure) -----------------------------------------------------------

def classes_to_profile(classes: list[ClassInfo], max_classes: int,
                       requested: list[str] | None = None) -> tuple[list[ClassInfo], int, int]:
    """Classes to profile, in order: requested, then regular by count, then
    infrastructure. Returns (chosen, metadata classes skipped, infrastructure classes moved last)."""
    requested = requested or []
    by_iri = {c.iri: c for c in classes}
    first = [by_iri.get(r, ClassInfo(r, None, False)) for r in requested]
    regular, infra, metadata = [], [], 0
    for c in classes:
        if c.iri in requested:
            continue
        if namespace(c.iri) in METADATA_NAMESPACES:
            metadata += 1
        elif c.count != 0 and is_safe_iri(c.iri):
            (infra if is_infrastructure(c.iri) else regular).append(c)
    return (first + regular + infra)[:max_classes], metadata, len(infra)


def sample_plan(info: ClassInfo, n: int, seed: int) -> tuple[str, list[tuple[int, int]]]:
    """(method, [(offset, limit), ...]) for sampling one class."""
    count = info.count
    if count is not None and info.count_exact and count <= n:
        return ALL, [(0, n)]
    if count is None or count <= n:
        return FIRST_N, [(0, n)]
    size = -(-n // SAMPLE_BLOCKS)                     # ceil
    max_start = min(count, MAX_OFFSET) - size
    if max_start < SAMPLE_BLOCKS:
        return FIRST_N, [(0, n)]
    rng = random.Random(f"{seed}:{info.iri}")         # same seed and class, same offsets
    offsets = sorted(rng.sample(range(max_start + 1), SAMPLE_BLOCKS))
    return RANDOM_OFFSET, [(o, size) for o in offsets]


def first_distinct(rows: list[dict], n: int) -> list[dict]:
    """The first n rows with distinct ?s (pure)."""
    seen, kept = set(), []
    for row in rows:
        term = row.get("s")
        key = (term["type"], term["value"]) if term else None
        if key is None or key in seen:
            continue
        seen.add(key)
        kept.append(row)
        if len(kept) == n:
            break
    return kept


# -- one class -------------------------------------------------------------------

def sample_subjects(client, info: ClassInfo, settings: Settings
                    ) -> tuple[str, list[str], int, list[str], str | None]:
    """Run the sample plan. Returns (method, IRI subjects, blank nodes, failure statuses, last error)."""
    method, plan = sample_plan(info, settings.sample, settings.seed)
    logger.debug("sample %s: %s %s", info.iri, method, plan)
    ask = 1 if method == ALL else OVERSAMPLE
    rows, statuses, error = [], [], None
    for offset, limit in plan:
        outcome = client.query(step_label(info.iri, "sample"),
                               sample_query(info.iri, limit * ask, settings.graph, settings.class_property, offset))
        if outcome.status == "ok":
            rows += first_distinct(outcome.rows, limit)
            continue
        statuses.append(step_status(outcome.status))
        error = outcome.error
        if outcome.status == "budget_exhausted":
            break
    if method == RANDOM_OFFSET and not rows and model.SKIPPED not in statuses:
        logger.debug("sample %s: every offset block failed, falling back to first-n", info.iri)
        method = FIRST_N
        outcome = client.query(step_label(info.iri, "sample"),
                               sample_query(info.iri, settings.sample * OVERSAMPLE, settings.graph,
                                            settings.class_property))
        if outcome.status == "ok":
            rows = first_distinct(outcome.rows, settings.sample)
        else:
            statuses.append(step_status(outcome.status))
            error = outcome.error

    subjects, bnodes = [], 0
    for row in rows:
        term = row.get("s")
        if not term:
            continue
        if term["type"] != "uri" or not is_safe_iri(term["value"]):
            bnodes += 1
        elif term["value"] not in subjects:
            subjects.append(term["value"])
    return method, subjects, bnodes, statuses, error


def profile_class(client, info: ClassInfo, settings: Settings
                  ) -> tuple[ClassProfile | None, profiling.Sample | None, str, str]:
    """Profile one class. Returns (profile, raw sample, status, message); profile
    and sample are None when nothing could be profiled."""
    class_iri, graph = info.iri, settings.graph

    # 1. Sample of subjects.
    method, subjects, bnodes, sample_statuses, error = sample_subjects(client, info, settings)
    if not subjects:
        if sample_statuses:
            return None, None, worst(*sample_statuses), f"sample failed: {error}"
        return None, None, model.UNSUPPORTED, f"no IRI instances to profile ({bnodes} blank node(s))"
    # Some offset blocks failing still leaves a usable sample: only running out of budget counts.
    statuses = [model.OK] + [s for s in sample_statuses if s == model.SKIPPED]

    # 2. Triples of the sample, in batches.
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
        return None, None, worst(*statuses), f"all {failed} triples batch(es) failed"
    triples = profiling.triples_from_rows(rows)

    # 3. Types of a subsample of IRI objects.
    to_check = profiling.objects_to_check(triples, class_property=settings.class_property)
    all_objects = list(dict.fromkeys(o for objs in to_check.values() for o in objs if is_safe_iri(o)))
    object_types, checked_ok = {}, set()
    for batch in chunks(all_objects, TYPE_BATCH):
        outcome = client.query(step_label(class_iri, "types"), types_query(batch, graph, settings.class_property))
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
                                   truncated=truncated, failed_batches=failed, sample_method=method)
    notes = [f"{prof.sample_size} instances ({method}), {len(prof.properties)} properties"]
    if bnodes:
        notes.append(f"{bnodes} blank-node instance(s) not profiled")
    if truncated:
        notes.append("truncated")
    if failed:
        notes.append(f"{failed} batch(es) failed")
    raw = profiling.Sample(class_iri, profiled, triples, object_types, checked_ok, truncated)
    return prof, raw, worst(*statuses), ", ".join(notes)


# -- the step --------------------------------------------------------------------

def run(client, ctx: Context) -> StepResult:
    discovery = ctx.discovery
    settings = ctx.settings
    candidates, metadata, moved = classes_to_profile(discovery.classes, settings.max_classes, settings.classes)
    if not candidates:
        return StepResult(NAME, model.OK, "no classes to profile")

    statuses = [model.OK]
    out_of_budget = False
    for i, info in enumerate(candidates):
        prof, raw, status, message = profile_class(client, info, settings)
        logger.debug("profile %s: %s (%s)", info.iri, status, message)
        if prof is not None:
            discovery.profiles.append(prof)
            ctx.samples[info.iri] = raw
        # A class with only blank-node instances is a known limitation, not a degraded run.
        statuses.append(model.OK if status == model.UNSUPPORTED else status)
        if status == model.SKIPPED:
            logger.debug("budget exhausted after %d of %d classes", i, len(candidates))
            out_of_budget = True
            break

    discovery.label_properties = profiling.detect_label_properties(discovery.profiles)

    parts = [f"{len(discovery.profiles)} of {len(candidates)} classes profiled (sample ≤ {settings.sample})"]
    if settings.classes:
        parts.append(f"{len(settings.classes)} requested first")
    if metadata:
        parts.append(f"{metadata} metadata class(es) skipped")
    if moved:
        parts.append(f"{moved} infrastructure class(es) moved last")
    truncated = sum(p.truncated for p in discovery.profiles)
    if truncated:
        parts.append(f"{truncated} truncated")
    failed = sum(1 for s in statuses if s in (model.ERROR, model.TIMEOUT))
    if failed:
        parts.append(f"{failed} class(es) with failed queries")
    if out_of_budget:
        parts.append("budget ran out")
    return StepResult(NAME, worst(*statuses), "; ".join(parts))

"""Step 6: declared ontologies, and labels/comments of the classes in use.

- owl:Ontology with label, title, versionIRI and versionInfo.
- rdfs:label / rdfs:comment of the discovered classes (the first
  LABELLED_CLASSES of them, in batches with VALUES). English or untagged
  values are preferred.
Namespaces are derived later, by the namespaces step, once property IRIs
are known from the profile.
"""

from __future__ import annotations

import logging

from baqueano import model, scope
from baqueano.context import Context, step_status, worst
from baqueano.model import ClassInfo, StepResult
from baqueano.rows import iri, node_id, value
from baqueano.vocabularies import is_safe_iri

logger = logging.getLogger(__name__)

NAME = "vocab"
ONTOLOGIES_STEP = "vocab:ontologies"
LABELS_STEP = "vocab:labels"
ONTOLOGIES_LIMIT = 100
LABELLED_CLASSES = 100
LABEL_BATCH = 50
PREFERRED_LANGUAGES = ("en", "")   # in order; "" = no language tag

PREFIXES = ("PREFIX owl: <http://www.w3.org/2002/07/owl#>\n"
            "PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>\n"
            "PREFIX dct: <http://purl.org/dc/terms/>\n")


def ontologies_query(graph: str | None) -> str:
    pattern = ("?ont a owl:Ontology . "
               "OPTIONAL { ?ont rdfs:label ?label } "
               "OPTIONAL { ?ont dct:title ?title } "
               "OPTIONAL { ?ont owl:versionIRI ?versionIRI } "
               "OPTIONAL { ?ont owl:versionInfo ?versionInfo }")
    return (PREFIXES + f"SELECT ?ont ?label ?title ?versionIRI ?versionInfo "
            f"WHERE {{ {scope.where(pattern, graph)} }} LIMIT {ONTOLOGIES_LIMIT}")


def labels_query(class_iris: list[str], graph: str | None) -> str:
    values = " ".join(f"<{c}>" for c in class_iris)
    pattern = "OPTIONAL { ?c rdfs:label ?label } OPTIONAL { ?c rdfs:comment ?comment }"
    return (PREFIXES + f"SELECT ?c ?label ?comment WHERE {{ VALUES ?c {{ {values} }} "
            f"{scope.where(pattern, graph)} }}")


def lang_rank(term: dict) -> int:
    """Lower is better: English, then untagged, then anything else."""
    lang = term.get("lang", "")
    return PREFERRED_LANGUAGES.index(lang) if lang in PREFERRED_LANGUAGES else len(PREFERRED_LANGUAGES)


def pick(terms: list[dict]) -> str | None:
    """Best value among candidate literals, by language preference."""
    if not terms:
        return None
    return min(terms, key=lambda t: (lang_rank(t), t["value"]))["value"]


def ontologies_from_rows(rows: list[dict]) -> list[dict]:
    """One dict per ontology, first value of each field (pure)."""
    ontologies: dict[str, dict] = {}
    labels: dict[str, list[dict]] = {}
    for row in rows:
        ont = node_id(row, "ont")
        if ont is None:
            continue
        entry = ontologies.setdefault(ont, {"iri": ont, "label": None, "version_iri": None, "version_info": None})
        for var in ("label", "title"):
            if row.get(var):
                labels.setdefault(ont, []).append(row[var])
        entry["version_iri"] = entry["version_iri"] or iri(row, "versionIRI")
        entry["version_info"] = entry["version_info"] or value(row, "versionInfo")
    for ont, entry in ontologies.items():
        entry["label"] = pick(labels.get(ont, []))
    return list(ontologies.values())


def apply_labels(classes: list[ClassInfo], rows: list[dict]) -> int:
    """Set label/comment on `classes` from label rows. Returns how many got a label (pure-ish)."""
    labels: dict[str, list[dict]] = {}
    comments: dict[str, list[dict]] = {}
    for row in rows:
        c = iri(row, "c")
        if c is None:
            continue
        if row.get("label"):
            labels.setdefault(c, []).append(row["label"])
        if row.get("comment"):
            comments.setdefault(c, []).append(row["comment"])
    labelled = 0
    for info in classes:
        info.label = pick(labels.get(info.iri, [])) or info.label
        info.comment = pick(comments.get(info.iri, [])) or info.comment
        labelled += info.label is not None
    return labelled


def run(client, ctx: Context) -> StepResult:
    discovery = ctx.discovery
    graph = ctx.settings.graph
    statuses, messages = [], []

    onts = client.query(ONTOLOGIES_STEP, ontologies_query(graph))
    if onts.status == "ok":
        discovery.ontologies = ontologies_from_rows(onts.rows)
        statuses.append(model.OK)
        messages.append(f"{len(discovery.ontologies)} ontology declaration(s)")
    else:
        statuses.append(step_status(onts.status))
        messages.append(f"ontology query failed: {onts.error}")

    targets = [c for c in discovery.classes if is_safe_iri(c.iri)][:LABELLED_CLASSES]
    label_rows, failed = [], 0
    for start in range(0, len(targets), LABEL_BATCH):
        batch = [c.iri for c in targets[start:start + LABEL_BATCH]]
        outcome = client.query(LABELS_STEP, labels_query(batch, graph))
        if outcome.status == "ok":
            label_rows.extend(outcome.rows)
        else:
            failed += 1
            statuses.append(step_status(outcome.status))
            if outcome.status == "budget_exhausted":
                break
    labelled = apply_labels(targets, label_rows)
    messages.append(f"{labelled} of {len(targets)} classes have a label"
                    + (f" ({failed} label batch(es) failed)" if failed else ""))
    return StepResult(NAME, worst(*statuses), "; ".join(messages))

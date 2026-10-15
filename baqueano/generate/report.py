"""report.md: readable summary of the discovery.

Opens with "How to read this": which figures are exact, which are declared
(VoID) or sampled, and what was missed. Then dataset, classes, vocabularies,
existing shapes, profiles, links and the files produced. Long lists are
capped; everything is in discovery.json.
"""

from __future__ import annotations

from baqueano import model
from baqueano.generate import thresholds as th
from baqueano.generate.queries import render as render_queries
from baqueano.model import ClassInfo, ClassProfile, Discovery
from baqueano.profiling import OBJECTS_PER_PROPERTY, RDF_TYPE
from baqueano.vocabularies import shorten

MAX_GRAPHS = 20
MAX_CLASSES = 50
MAX_PROPERTIES = 25
MAX_LINKS = 30
MAX_SHAPES = 30


# -- formatting helpers --------------------------------------------------------

def cell(text) -> str:
    """Markdown table cell: pipes escaped, newlines flattened."""
    return str(text).replace("|", "\\|").replace("\n", " ")


def code(iri: str) -> str:
    """IRI as `prefix:local`, or `<full IRI>` when the namespace is unknown."""
    return f"`{shorten(iri)}`"


def table(headers: list[str], rows: list[list]) -> list[str]:
    lines = ["| " + " | ".join(headers) + " |", "|" + "---|" * len(headers)]
    lines += ["| " + " | ".join(cell(c) for c in row) + " |" for row in rows]
    return lines


def more(shown: int, total: int, what: str) -> list[str]:
    return [f"", f"*{total - shown} more {what} not shown; see discovery.json.*"] if total > shown else []


def count_cell(info: ClassInfo) -> str:
    if info.count is None:
        return "unknown (sampled)"
    return f"{info.count:,}" if info.count_exact else f"{info.count:,} (VoID)"


# -- sections ------------------------------------------------------------------

def header(d: Discovery) -> list[str]:
    lines = [f"# Baqueano report: {d.endpoint}", "",
             f"- Explored: {d.started_at}"]
    if d.graph_scope:
        lines.append(f"- Scope: graph `<{d.graph_scope}>` only")
    if d.server_header:
        lines.append(f"- Server: {d.server_header}")
    lines.append(f"- Service description: {'yes' if d.has_service_description else 'no'}")
    return lines + [""]


def how_to_read(d: Discovery) -> list[str]:
    exact, estimated, missed = [], [], []

    if d.triple_count is not None:
        (exact if d.triple_count_exact else estimated).append(
            "total triples" + ("" if d.triple_count_exact else " (declared in VoID, may be stale)"))
    n_exact = sum(1 for c in d.classes if c.count_exact)
    n_void = sum(1 for c in d.classes if c.count is not None and not c.count_exact)
    n_unknown = sum(1 for c in d.classes if c.count is None)
    if n_exact:
        exact.append(f"instance counts of {n_exact} classes")
    if n_void:
        estimated.append(f"instance counts of {n_void} classes (declared in VoID)")
    if n_unknown:
        estimated.append(f"{n_unknown} classes were found by sampling, without counts")
    if d.graphs and d.graph_scope is None:
        exact.append("the list of named graphs (up to the listing limit)")
    if d.profiles:
        sizes = sorted({p.sample_size for p in d.profiles})
        size_text = str(sizes[0]) if len(sizes) == 1 else f"{sizes[0]}–{sizes[-1]}"
        estimated.append(f"property profiles: from the first {size_text} instances of each class "
                         "(not random), so support and cardinality are estimates")
        estimated.append(f"target classes and links: from up to {OBJECTS_PER_PROPERTY} checked objects "
                         "per property")
        estimated.append("inferred shapes (shapes.ttl): observations from those samples, not rules")
    for s in d.steps:
        if s.status in (model.SAMPLED, model.TIMEOUT, model.SKIPPED, model.ERROR):
            missed.append(f"**{s.name}** ({s.status}): {s.message or ''}")
    for p in d.profiles:
        if p.truncated:
            missed.append(f"profile of {code(p.class_iri)} is truncated: a batch hit its result limit")
        if p.failed_batches:
            missed.append(f"profile of {code(p.class_iri)}: {p.failed_batches} batch(es) failed, "
                          "their instances are not counted")

    lines = ["## How to read this", ""]
    lines += ["**Exact:** " + ("; ".join(exact) if exact else "nothing (no exact figure could be computed)") + ".",
              "",
              "**Estimated:** " + ("; ".join(estimated) if estimated else "nothing") + ".",
              ""]
    if missed:
        lines += ["**Missed or incomplete:**", ""] + [f"- {m}" for m in missed] + [""]
    else:
        lines += ["**Missed:** nothing, every step completed.", ""]
    return lines


def steps_section(d: Discovery) -> list[str]:
    rows = [[s.name, s.status, s.message or ""] for s in d.steps]
    return ["## Discovery steps", ""] + table(["Step", "Status", "Details"], rows) + [""]


def dataset_section(d: Discovery) -> list[str]:
    if d.triple_count is None:
        size = "unknown"
    else:
        size = f"{d.triple_count:,}" + ("" if d.triple_count_exact else " (declared in VoID)")
    lines = ["## Dataset", "", f"- Triples: {size}"]
    if d.graph_scope:
        lines.append(f"- Restricted to graph `<{d.graph_scope}>`")
    elif d.graphs:
        lines.append(f"- Named graphs: {len(d.graphs)}")
        lines += [f"  - `<{g}>`" for g in d.graphs[:MAX_GRAPHS]]
        if len(d.graphs) > MAX_GRAPHS:
            lines.append(f"  - … {len(d.graphs) - MAX_GRAPHS} more")
    else:
        lines.append("- Named graphs: none found")
    if d.void:
        lines.append(f"- VoID: {len(d.void.get('datasets', {}))} dataset description(s), "
                     f"{len(d.void.get('class_partitions', {}))} class partition(s)")
    return lines + [""]


def classes_section(d: Discovery) -> list[str]:
    if not d.classes:
        return ["## Classes", "", "No classes found.", ""]
    profiled = {p.class_iri for p in d.profiles}
    rows = [[code(c.iri), c.label or "", count_cell(c), "yes" if c.iri in profiled else ""]
            for c in d.classes[:MAX_CLASSES]]
    return (["## Classes", "", f"{len(d.classes)} classes, most populated first.", ""]
            + table(["Class", "Label", "Instances", "Profiled"], rows)
            + more(MAX_CLASSES, len(d.classes), "classes") + [""])


def vocabularies_section(d: Discovery) -> list[str]:
    lines = ["## Vocabularies", ""]
    if d.vocabularies:
        rows = [[f"`{v['namespace']}`", v["prefix"] or "", v["name"] or "", v["terms"],
                 "yes" if v["declared_in_void"] else ""] for v in d.vocabularies]
        lines += table(["Namespace", "Prefix", "Vocabulary", "Terms seen", "In VoID"], rows) + [""]
    else:
        lines += ["No namespaces derived.", ""]
    if d.ontologies:
        lines += ["Declared ontologies (`owl:Ontology`):", ""]
        for o in d.ontologies:
            extra = ", ".join(x for x in (o.get("label"), o.get("version_info") and f"version {o['version_info']}") if x)
            lines.append(f"- `<{o['iri']}>`" + (f": {extra}" if extra else ""))
        lines.append("")
    return lines


def found_shapes_section(d: Discovery) -> list[str]:
    if not d.found_shapes:
        return ["## Shapes published in the endpoint", "", "None found.", ""]
    rows = [[code(s["shape"]) if not s["shape"].startswith("_:") else s["shape"],
             code(s["target_class"]) if s["target_class"] else ""] for s in d.found_shapes[:MAX_SHAPES]]
    copied = "copied to `found-shapes.ttl`" if d.found_shapes_ttl else "could not be copied"
    return (["## Shapes published in the endpoint", "", f"{len(d.found_shapes)} shape(s), {copied}.", ""]
            + table(["Shape", "Target class"], rows) + more(MAX_SHAPES, len(d.found_shapes), "shapes") + [""])


def values_cell(pp) -> str:
    """Short description of what the values look like."""
    parts = []
    if pp.literal_objects:
        top = sorted(pp.datatypes.items(), key=lambda kv: -kv[1])[:2]
        parts.append(", ".join(shorten(dt) for dt, _ in top) or "literal")
    if pp.languages:
        parts.append("@" + "/".join(sorted(pp.languages, key=lambda k: -pp.languages[k])[:4]))
    if pp.iri_objects:
        targets = sorted(pp.target_classes.items(), key=lambda kv: -kv[1])[:2]
        parts.append("→ " + ", ".join(shorten(t) for t, _ in targets) if targets else "IRI")
    if pp.bnode_objects:
        parts.append("blank node")
    return "; ".join(parts)


def profile_section(d: Discovery, prof: ClassProfile) -> list[str]:
    info = next((c for c in d.classes if c.iri == prof.class_iri), None)
    title = code(prof.class_iri) + (f" ({info.label})" if info and info.label else "")
    noun = "instance" if prof.sample_size == 1 else "instances"
    notes = [f"Sample: {prof.sample_size} {noun} ({prof.sample_method})"]
    if prof.truncated:
        notes.append("**truncated**")
    if prof.failed_batches:
        notes.append(f"**{prof.failed_batches} batch(es) failed**")
    if prof.example_instance:
        notes.append(f"example: `<{prof.example_instance}>`")
    props = [pp for pp in prof.properties if pp.path != RDF_TYPE]
    rows = [[code(pp.path), f"{pp.support:.2f}", pp.max_values_per_subject, values_cell(pp)]
            for pp in props[:MAX_PROPERTIES]]
    return ([f"### {title}", "", ". ".join(notes) + ".", ""]
            + table(["Property", "Support", "Max per instance", "Values"], rows)
            + more(MAX_PROPERTIES, len(props), "properties") + [""])


def profiles_section(d: Discovery) -> list[str]:
    if not d.profiles:
        return ["## Class profiles", "", "No class was profiled.", ""]
    lines = ["## Class profiles", "",
             "Support = share of sampled instances that have the property. "
             "Max per instance = most values seen on one instance.", ""]
    if d.label_properties:
        lines += ["Label properties seen: " + ", ".join(code(p) for p in d.label_properties) + ".", ""]
    for prof in d.profiles:
        lines += profile_section(d, prof)
    return lines


def links_section(d: Discovery) -> list[str]:
    if not d.links:
        return ["## Links between classes", "", "No links found.", ""]
    rows = [[code(link.source_class), code(link.path), code(link.target_class), f"{link.support:.2f}"]
            for link in d.links[:MAX_LINKS]]
    return (["## Links between classes", "",
             "Support = estimated share of sampled source instances linking to the target class.", ""]
            + table(["From", "Property", "To", "Support"], rows) + more(MAX_LINKS, len(d.links), "links") + [""])


def files_section(d: Discovery) -> list[str]:
    lines = ["## Files", "",
             "- `discovery.json`: everything discovered (the other files are generated from it)",
             "- `queries.log`: every query sent, one JSON line each; paste a query into a SPARQL editor to replay it",
             "- `shapes.ttl`: inferred draft SHACL shapes (`sh:Info`, with `baq:support`)",
             f"- `schema.mmd`: Mermaid class diagram (up to {th.DIAGRAM_MAX_CLASSES} classes)"]
    if d.found_shapes_ttl:
        lines.append("- `found-shapes.ttl`: shapes published in the endpoint")
    lines += ["- `queries/`: starter queries, ready to run:"]
    lines += [f"  - `{name}`" for name in render_queries(d)]
    return lines + [""]


def render(discovery: Discovery) -> str:
    sections = [header, how_to_read, steps_section, dataset_section, classes_section, vocabularies_section,
                found_shapes_section, profiles_section, links_section, files_section]
    lines: list[str] = []
    for section in sections:
        lines += section(discovery)
    return "\n".join(lines).rstrip() + "\n"

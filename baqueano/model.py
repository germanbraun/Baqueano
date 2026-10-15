"""Discovery data model: dataclasses only, no I/O.

Everything Baqueano learns about an endpoint ends up in a Discovery, which is
what discovery.json holds and what the generators read.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

# Step statuses (StepResult.status).
OK = "ok"
SAMPLED = "sampled"          # the exact query failed, a sample was used
TIMEOUT = "timeout"
SKIPPED = "skipped"          # out of budget
UNSUPPORTED = "unsupported"  # the endpoint does not offer this
ERROR = "error"              # HTTP or parse failure


@dataclass
class ClassInfo:
    iri: str
    count: int | None          # None when only found by sampling
    count_exact: bool
    label: str | None = None
    comment: str | None = None


@dataclass
class PropertyProfile:
    path: str
    support: float             # subjects having the property / sample size
    max_values_per_subject: int
    iri_objects: int
    literal_objects: int
    datatypes: dict[str, int] = field(default_factory=dict)
    languages: dict[str, int] = field(default_factory=dict)
    target_classes: dict[str, int] = field(default_factory=dict)


@dataclass
class ClassProfile:
    class_iri: str
    sample_size: int
    sample_method: str         # "first-n" in v0
    truncated: bool
    example_instance: str | None
    properties: list[PropertyProfile] = field(default_factory=list)


@dataclass
class Link:
    source_class: str
    path: str
    target_class: str
    support: float


@dataclass
class StepResult:
    name: str
    status: str                # ok | sampled | timeout | skipped | unsupported | error
    message: str | None = None


@dataclass
class Discovery:
    endpoint: str
    started_at: str
    graph_scope: str | None = None
    steps: list[StepResult] = field(default_factory=list)
    server_header: str | None = None
    has_service_description: bool = False
    void: dict | None = None
    found_shapes: list[str] = field(default_factory=list)
    graphs: list[str] = field(default_factory=list)
    triple_count: int | None = None
    classes: list[ClassInfo] = field(default_factory=list)
    ontologies: list[dict] = field(default_factory=list)
    vocabularies: list[dict] = field(default_factory=list)  # namespace, known prefix, number of terms
    label_properties: list[str] = field(default_factory=list)
    profiles: list[ClassProfile] = field(default_factory=list)
    links: list[Link] = field(default_factory=list)


def discovery_to_dict(discovery: Discovery) -> dict:
    """Plain dict ready for json.dumps."""
    return asdict(discovery)


def discovery_from_dict(data: dict) -> Discovery:
    """Inverse of discovery_to_dict (for reading a saved discovery.json)."""
    data = dict(data)
    data["steps"] = [StepResult(**s) for s in data.get("steps", [])]
    data["classes"] = [ClassInfo(**c) for c in data.get("classes", [])]
    data["links"] = [Link(**link) for link in data.get("links", [])]
    profiles = []
    for p in data.get("profiles", []):
        p = dict(p)
        p["properties"] = [PropertyProfile(**pp) for pp in p.get("properties", [])]
        profiles.append(ClassProfile(**p))
    data["profiles"] = profiles
    return Discovery(**data)

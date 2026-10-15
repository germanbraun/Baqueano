import json

from baqueano.generate import report
from baqueano.model import ClassInfo, Discovery, StepResult, discovery_from_dict, discovery_to_dict
from tests.sample_discovery import sample_discovery


def section(text: str, title: str) -> str:
    """Body of the '## title' section."""
    start = text.index(f"## {title}")
    end = text.find("\n## ", start + 1)
    return text[start:end if end != -1 else None]


def test_starts_with_how_to_read():
    text = report.render(sample_discovery())
    assert text.startswith("# Baqueano report: http://example.org/sparql\n")
    headings = [line for line in text.splitlines() if line.startswith("## ")]
    assert headings[0] == "## How to read this"
    assert headings == ["## How to read this", "## Discovery steps", "## Dataset", "## Classes",
                        "## Vocabularies", "## Shapes published in the endpoint", "## Class profiles",
                        "## Links between classes", "## Files"]


def test_how_to_read_separates_exact_estimated_and_missed():
    d = sample_discovery()
    d.steps.append(StepResult("vocab", "timeout", "ontology query failed: no answer after 30.0s"))
    block = section(report.render(d), "How to read this")
    assert "**Exact:** total triples; instance counts of 1 classes; the list of named graphs" in block
    assert "instance counts of 1 classes (declared in VoID)" in block
    assert "1 classes were found by sampling, without counts" in block
    assert "first 50–200 instances of each class (not random)" in block
    assert "**vocab** (timeout): ontology query failed" in block
    assert "profile of `schema:Place` is truncated" in block


def test_fallback_steps_are_listed_as_incomplete():
    d = sample_discovery()
    d.steps.append(StepResult("classes", "sampled", "count query timeout; 3 classes declared in VoID"))
    block = section(report.render(d), "How to read this")
    assert "**classes** (sampled): count query timeout" in block


def test_nothing_missed():
    d = sample_discovery()
    d.profiles[1].truncated = False
    assert "**Missed:** nothing, every step completed." in report.render(d)


def test_classes_table():
    block = section(report.render(sample_discovery()), "Classes")
    assert "| `schema:Person` | Person | 200 | yes |" in block
    assert "| `schema:Place` |  | 50 (VoID) | yes |" in block
    assert "| `<http://unknown.org/vocab/Organisation>` |  | unknown (sampled) |  |" in block


def test_profile_tables():
    block = section(report.render(sample_discovery()), "Class profiles")
    assert "### `schema:Person` (Person)" in block
    assert "Sample: 200 instances (first-n). example: `<http://ex/person/1>`." in block
    assert "| `schema:birthDate` | 0.97 | 1 | xsd:date |" in block
    assert "| `schema:birthPlace` | 0.97 | 1 | → schema:Place |" in block
    assert "| `schema:nick` | 0.50 | 2 | rdf:langString; @en/es |" in block
    assert "rdf:type" not in block
    assert "Sample: 50 instances (first-n). **truncated**" in block


def test_links_and_files():
    text = report.render(sample_discovery())
    assert "| `schema:Person` | `schema:birthPlace` | `schema:Place` | 0.97 |" in section(text, "Links between classes")
    assert "  - `12-person-table.rq`" in section(text, "Files")


def test_pipes_are_escaped():
    d = sample_discovery()
    d.classes[0].label = "Person | human"
    assert "Person \\| human" in report.render(d)


def test_long_lists_are_capped():
    d = sample_discovery()
    d.classes = [ClassInfo(f"http://ex/C{i}", 100 - i, True) for i in range(report.MAX_CLASSES + 7)]
    assert "*7 more classes not shown; see discovery.json.*" in report.render(d)


def test_failed_probe_still_renders():
    d = Discovery(endpoint="http://down.example/sparql", started_at="t",
                  steps=[StepResult("probe", "error", "endpoint did not answer: HTTP 401 -> needs authentication")])
    text = report.render(d)
    assert "**probe** (error): endpoint did not answer: HTTP 401" in text
    assert "Triples: unknown" in text
    assert "No classes found." in text


def test_reads_only_what_discovery_json_holds():
    d = sample_discovery()
    reloaded = discovery_from_dict(json.loads(json.dumps(discovery_to_dict(d))))
    assert report.render(reloaded) == report.render(d)

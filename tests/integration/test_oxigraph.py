"""End-to-end: `baqueano explore` against a real Oxigraph loaded with data/sample.trig.

Needs the server from docker-compose.yml (skipped otherwise):

    docker compose -f tests/integration/docker-compose.yml up -d

Set BAQUEANO_OXIGRAPH to use another Oxigraph base URL. The data is replaced
on every run (CLEAR ALL), so never point this at a store you care about.
"""

import json
import os
from pathlib import Path

import httpx
import pytest
from rdflib import Dataset, Graph, URIRef
from rdflib.namespace import SH, XSD

from baqueano import cli

BASE = os.environ.get("BAQUEANO_OXIGRAPH", "http://127.0.0.1:7878")
QUERY_URL = f"{BASE}/query"
DATA = Path(__file__).parent / "data" / "sample.trig"
S = "https://schema.org/"
PLACES = "http://example.org/graph/places"
META = "http://example.org/graph/meta"


def oxigraph_up() -> bool:
    try:
        return httpx.get(f"{BASE}/", timeout=2).status_code < 500
    except httpx.HTTPError:
        return False


pytestmark = pytest.mark.skipif(not oxigraph_up(), reason=f"no Oxigraph at {BASE} (see docker-compose.yml)")


@pytest.fixture(scope="module", autouse=True)
def loaded():
    httpx.post(f"{BASE}/update", data={"update": "CLEAR ALL"}, timeout=10).raise_for_status()
    httpx.post(f"{BASE}/store", content=DATA.read_bytes(), headers={"Content-Type": "application/trig"},
               timeout=10).raise_for_status()


def explore(out: Path, *extra: str) -> tuple[int, dict]:
    code = cli.main(["explore", QUERY_URL, "--out", str(out), "--delay", "0", "--budget", "60", *extra])
    return code, json.loads((out / "discovery.json").read_text())


@pytest.fixture(scope="module")
def run(tmp_path_factory):
    out = tmp_path_factory.mktemp("oxigraph")
    code, discovery = explore(out)
    return out, code, discovery


def by_iri(items, key="iri"):
    return {item[key]: item for item in items}


def prop(discovery, class_iri, path):
    profile = next(p for p in discovery["profiles"] if p["class_iri"] == class_iri)
    return next(pp for pp in profile["properties"] if pp["path"] == path)


def test_complete_run(run):
    _, code, d = run
    assert code == cli.EXIT_OK, d["steps"]
    assert [s["status"] for s in d["steps"]] == ["ok"] * 10


def test_graphs_and_size(run):
    _, _, d = run
    assert set(d["graphs"]) == {PLACES, META}
    assert d["triple_count_exact"] is True
    expected = len(Dataset().parse(DATA, format="trig"))   # every quad, union of all graphs
    assert d["triple_count"] == expected


def test_classes_with_exact_counts(run):
    _, _, d = run
    classes = by_iri(d["classes"])
    assert {c: classes[S + c]["count"] for c in ("Person", "Organization", "Place", "PostalAddress")} == \
        {"Person": 10, "Organization": 3, "Place": 4, "PostalAddress": 3}
    assert all(c["count_exact"] for c in d["classes"])
    assert classes[S + "Person"]["label"] == "Person"          # English preferred over "Persona"@es


def test_void_ontology_and_found_shapes(run):
    out, _, d = run
    assert d["void"]["triples"] == 999
    assert d["void"]["class_partitions"] == {S + "Person": 10}
    assert [o["label"] for o in d["ontologies"]] == ["Baqueano test ontology"]
    assert d["found_shapes"] == [{"shape": "http://example.org/PersonShape", "target_class": S + "Person"}]
    found = Graph().parse(out / "found-shapes.ttl")
    assert (None, SH.minCount, None) in found                  # property shape copied (second level)


def test_profiles(run):
    _, _, d = run
    assert {p["class_iri"] for p in d["profiles"]} == {S + "Person", S + "Organization", S + "Place"}
    name = prop(d, S + "Person", S + "name")
    assert (name["support"], name["max_values_per_subject"]) == (1.0, 1)
    assert prop(d, S + "Person", S + "birthDate")["support"] == 0.9
    knows = prop(d, S + "Person", S + "knows")
    assert (knows["support"], knows["max_values_per_subject"], knows["target_classes"]) == (0.5, 2, {S + "Person": 5})
    nick = prop(d, S + "Person", S + "nick")
    assert (nick["support"], nick["languages"]) == (0.3, {"es": 2, "en": 2})
    works = prop(d, S + "Person", S + "worksFor")
    assert works["target_classes"] == {S + "Organization": 3}
    address = prop(d, S + "Organization", S + "address")
    assert (address["bnode_objects"], address["iri_objects"]) == (3, 0)
    assert prop(d, S + "Place", S + "containedInPlace")["support"] == 0.75
    assert d["label_properties"] == ["http://www.w3.org/2000/01/rdf-schema#label", S + "name"]


def test_links(run):
    _, _, d = run
    links = {(link["source_class"], link["path"], link["target_class"]): link["support"] for link in d["links"]}
    assert links == {
        (S + "Person", S + "worksFor", S + "Organization"): 1.0,
        (S + "Organization", S + "location", S + "Place"): 1.0,
        (S + "Place", S + "containedInPlace", S + "Place"): 0.75,
        (S + "Person", S + "knows", S + "Person"): 0.5,
    }


def test_inferred_shapes(run):
    out, _, _ = run
    g = Graph().parse(out / "shapes.ttl")
    person = URIRef("urn:baqueano:shape:Person")

    def constraint(path, predicate):
        for node in g.objects(person, SH.property):
            if (node, SH.path, URIRef(S + path)) in g:
                return g.value(node, predicate)
        raise AssertionError(f"no property shape for {path}")

    assert constraint("worksFor", SH["class"]) == URIRef(S + "Organization")
    assert constraint("worksFor", SH.minCount).toPython() == 1
    assert constraint("birthDate", SH.datatype) == XSD.date
    assert constraint("birthDate", SH.minCount) is None        # 0.9 < 0.95
    assert constraint("knows", SH.maxCount) is None            # someone knows two people


def test_generated_queries_run_and_return_rows(run):
    out, _, _ = run
    files = sorted((out / "queries").glob("*.rq"))
    assert len(files) >= 10
    for path in files:
        response = httpx.post(QUERY_URL, data={"query": path.read_text()},
                              headers={"Accept": "application/sparql-results+json"}, timeout=10)
        assert response.status_code == 200, (path.name, response.text[:300])
        assert response.json()["results"]["bindings"], f"{path.name} returned no rows"


def test_report_written(run):
    out, _, _ = run
    report = (out / "report.md").read_text()
    # The only gap is the sh:or the validator does not support.
    missed = report.split("**Missed or incomplete:**")[1].split("## Discovery steps")[0]
    assert [line for line in missed.splitlines() if line.startswith("- ")] == \
        ["- 1 published shape constraint(s) could not be checked (see Data quality)"]
    assert "| `schema:Person` | Person | 10 | yes |" in report


def test_graph_scope(tmp_path):
    code, d = explore(tmp_path, "--graph", PLACES)
    assert code == cli.EXIT_OK, d["steps"]
    assert [c["iri"] for c in d["classes"]] == [S + "Place"]
    assert d["graphs"] == [PLACES]
    assert [p["class_iri"] for p in d["profiles"]] == [S + "Place"]
    assert d["void"] is None and d["found_shapes"] == []    # those live in another graph


def test_degraded_by_tiny_budget(tmp_path):
    code, d = explore(tmp_path, "--budget", "1.5", "--delay", "0.3")
    assert code == cli.EXIT_DEGRADED
    assert "skipped" in {s["status"] for s in d["steps"]}
    assert (tmp_path / "report.md").exists()


def test_validation_against_published_shape(run):
    _, _, d = run
    found = {(r["path"], r["component"]): r for r in d["validation"] if r["source"] == "found"}
    assert {k: (r["checked"], r["violations"]) for k, r in found.items()} == {
        (S + "name", "minCount"): (10, 0),
        (S + "birthDate", "minCount"): (10, 1),
        (S + "email", "pattern"): (10, 0),
        (S + "knows", "class"): (10, 0),
    }
    assert found[(S + "birthDate", "minCount")]["examples"] == ["http://example.org/p10"]
    assert [(n["path"], n["component"]) for n in d["validation_not_checked"]] == [(S + "nick", "or")]


def test_validation_section_in_report(run):
    out, _, _ = run
    report = (out / "report.md").read_text()
    assert "## Data quality" in report
    assert "`<http://example.org/p10>`" in report

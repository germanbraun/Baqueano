# Baqueano — project guide and v0

15 Oct 2026 · German Braun

## Vision

Baqueano is a command-line tool that, given an unknown SPARQL endpoint, discovers within minutes which data and vocabularies sit behind it, and leaves a report, a diagram, draft SHACL shapes and ready-to-run queries.

> Baqueano: a pathfinder for unknown SPARQL endpoints.

**The problem:** facing a new endpoint, you don't know its classes, properties or graphs, so you query blind. Existing tools either scan the whole dataset (and time out on large endpoints) or are interactive explorers that leave no reusable summary.

**What makes Baqueano different:**

- **Progressive discovery on a budget:** cheap queries first, sampling when expensive ones fail, never hangs.
- **Transparency:** every figure in the report says whether it is exact or comes from a sample.
- **Actionable output:** starter `.rq` queries and SHACL shapes the user can edit and reuse.
- Personal, independent project, unrelated to any commercial platform.

## v0 scope

The v0 has a single command, `baqueano explore`, which runs the full discovery against an endpoint and writes an output folder.

**Included:**

- Endpoint probe, plus Service Description and VoID when available.
- Named graphs, classes with counts (or a sample), vocabularies and declared ontologies.
- Per-class profile by sampling: properties, support, observed cardinality, value types.
- Links between classes.
- SHACL shapes already in the endpoint, and inferred draft shapes.
- Outputs: Markdown report, Mermaid diagram, `shapes.ttl`, `.rq` queries, `discovery.json` and a query log.

**Not included (later):**

- Validating data against the shapes.
- Web interface or HTML report.
- Incoming properties (who points to a class); outgoing only.
- Engine-specific server-side timeouts.
- Queries to remote endpoints via `SERVICE` (Baqueano never generates them).
- LLM integration.

## Command-line usage

One command with sensible defaults; everything else is optional.

```bash
baqueano explore https://example.org/sparql --out ./baqueano-out
```

| Option | Default | Purpose |
|---|---|---|
| `--out DIR` | `./baqueano-out` | Output folder |
| `--budget SEC` | 300 | Maximum total discovery time |
| `--timeout SEC` | 30 | Per-query timeout |
| `--sample N` | 200 | Instances sampled per class |
| `--max-classes N` | 30 | Classes to profile (the most populated) |
| `--graph IRI` | none | Restrict discovery to one named graph |
| `--delay SEC` | 0.5 | Pause between queries |
| `--header "K: V"` | none | Extra header, repeatable (e.g. authentication) |
| `--user-agent TEXT` | `baqueano/0.1 (+repo URL)` | Identification towards the endpoint |
| `--debug` | off | Detailed console logging |

**Exit codes:** 0 discovery complete, 1 complete with degraded or skipped steps, 2 error (endpoint unreachable, invalid arguments).

For credentials, prefer environment variables (`BAQUEANO_HEADER_AUTHORIZATION`) over `--header`, so they don't end up in shell history.

## Architecture

Three separate layers: **steps** discover, **`discovery.json`** stores, **generators** produce outputs. Only `client.py` touches the network and only `cli.py` writes files.

The CLI runs the steps in order; they query the endpoint through the client and fill the model. At the end the CLI renders every output from it.

Core data model (`model.py`, dataclasses only, no I/O):

```python
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
    datatypes: dict[str, int]
    languages: dict[str, int]
    target_classes: dict[str, int]

@dataclass
class ClassProfile:
    class_iri: str
    sample_size: int
    sample_method: str         # "first-n" in v0
    truncated: bool
    example_instance: str | None
    properties: list[PropertyProfile]

@dataclass
class Link:
    source_class: str
    path: str
    target_class: str
    support: float

@dataclass
class StepResult:
    name: str
    status: str                # ok | sampled | timeout | skipped | unsupported
    message: str | None

@dataclass
class Discovery:
    endpoint: str
    started_at: str
    graph_scope: str | None
    steps: list[StepResult]
    server_header: str | None
    has_service_description: bool
    void: dict | None
    found_shapes: list[str]
    graphs: list[str]
    triple_count: int | None
    classes: list[ClassInfo]
    ontologies: list[dict]
    vocabularies: list[dict]   # namespace, known prefix, number of terms
    label_properties: list[str]
    profiles: list[ClassProfile]
    links: list[Link]
```

**Principles for easy debugging:**

- Expected failures (timeout, HTTP, budget) are statuses, not exceptions.
- Every step and every generator can run on its own, with a `FakeClient` or a saved `discovery.json`.
- `queries.log` lets you reproduce any query by pasting it into a SPARQL editor.
- `--debug` logs every fallback decision and every threshold applied.

## Discovery pipeline

Eight steps, cheapest first. Each step returns its result plus a status: `ok`, `sampled` (exact query failed, a sample was used), `timeout`, `skipped` (out of budget) or `unsupported`. A failing step never stops the pipeline.

With `--graph`, every pattern is wrapped in `GRAPH <iri> { ... }`.

1. **Probe.** `ASK { ?s ?p ?o }` confirms the endpoint answers. A GET to the endpoint without query and with `Accept: text/turtle` tries to fetch the Service Description. The `Server` header is kept as a hint of the engine.

2. **VoID.** If present, it is used for counts and partitions and saves part of steps 4 and 6.

   ```sparql
   PREFIX void: <http://rdfs.org/ns/void#>
   SELECT ?ds ?p ?o WHERE { ?ds a void:Dataset ; ?p ?o } LIMIT 500
   ```

3. **Existing shapes.** Cheap and very valuable: what the authors declared.

   ```sparql
   PREFIX sh: <http://www.w3.org/ns/shacl#>
   SELECT ?shape ?target WHERE {
     ?shape a sh:NodeShape .
     OPTIONAL { ?shape sh:targetClass ?target }
   } LIMIT 200
   ```

   If there are results, a `CONSTRUCT { ?s ?p ?o }` limited to those shapes and their properties (two levels) copies them to `found-shapes.ttl`.

4. **Graphs and size.**

   ```sparql
   SELECT DISTINCT ?g WHERE { GRAPH ?g { ?s ?p ?o } } LIMIT 100
   SELECT (COUNT(*) AS ?n) WHERE { ?s ?p ?o }
   ```

   The total count is optional: on timeout, the report says "unknown".

5. **Classes.** Counts first; on timeout, a sample without counts.

   ```sparql
   SELECT ?class (COUNT(?s) AS ?n) WHERE { ?s a ?class }
   GROUP BY ?class ORDER BY DESC(?n) LIMIT 500

   # fallback
   SELECT DISTINCT ?class WHERE { ?s a ?class } LIMIT 500
   ```

6. **Vocabularies and ontologies.** Look for `owl:Ontology` with its label and version, and declared classes (`owl:Class`, `rdfs:Class`) with their `rdfs:label` and `rdfs:comment`. Namespaces are derived from class and property IRIs (split at the last `#` or `/`) and matched against a table of known vocabularies bundled with the package (schema.org, FOAF, SKOS, Dublin Core, OWL, RDFS, PROV, GeoSPARQL, Wikidata, etc.). No prefix.cc lookup in v0.

7. **Per-class profile** (for the `--max-classes` most populated):
   1. Subject sample: `SELECT ?s WHERE { ?s a <C> } LIMIT N`. Not random (the first ones the engine returns), and the report says so.
   2. Triples of the sample, in batches of 50 subjects using `VALUES ?s { ... } ?s ?p ?o`, with `LIMIT 10000` per batch; if the limit is hit, the profile is marked truncated.
   3. Types of IRI objects: `VALUES ?o { ... } ?o a ?t`, in batches.
   4. In Python: support per property, max values per subject, counters for datatype, language and target class.

8. **Links between classes.** Comes from step 7 with no new queries: every property whose objects have a class defines an edge Class A → property → Class B, with its support.

Label properties detected in the profile (`rdfs:label`, `skos:prefLabel`, `schema:name`, `dct:title`, `foaf:name`) are stored separately: the generated queries use them.

## Outputs

Everything lands in one folder, whether or not the discovery completes: whatever was missed is listed as skipped in the report.

```
baqueano-out/
  report.md            readable summary: endpoint, graphs, classes, vocabularies, profiles, warnings
  schema.mmd           Mermaid diagram (classDiagram) of classes and links
  shapes.ttl           inferred draft SHACL shapes, with support annotations
  found-shapes.ttl     shapes that already existed in the endpoint (if any)
  queries/
    00-overview.rq     classes with counts, graphs
    10-<class>-list.rq
    11-<class>-example.rq
    12-<class>-table.rq
    20-<classA>-to-<classB>.rq
  discovery.json       everything discovered, raw (for debugging and other tools)
  queries.log          one JSON line per query sent: step, text, duration, status, rows
```

`report.md` opens with a "how to read this" block: what is exact, what is sampled and what was skipped. Class file names use the IRI's local name, lowercased and hyphenated.

`discovery.json` is the source of truth: the generators (report, diagram, shapes, queries) read only from it. That makes it possible to regenerate outputs without querying the endpoint again, with a future `baqueano render discovery.json`.

## SHACL shape inference

Inferred shapes describe what was observed in a sample, not rules: every constraint carries its evidence and severity `sh:Info`. They are built from the step 7 profile, with no extra queries.

| Constraint | Proposed when | Default threshold |
|---|---|---|
| property included | support ≥ threshold | 0.05 |
| `sh:minCount 1` | support ≥ threshold | 0.95 |
| `sh:maxCount 1` | no sampled subject has more than one value | — |
| `sh:datatype` | one datatype covers ≥ threshold of the literals | 0.95 |
| `sh:class` | one target class covers ≥ threshold of the IRIs | 0.95 |
| `sh:nodeKind` | when neither `sh:datatype` nor `sh:class` applies (`sh:IRI`, `sh:Literal`, `sh:IRIOrLiteral`) | — |
| `sh:languageIn` | there are language-tagged literals | — |

Thresholds live in a single module as named constants, so they are easy to tune and test.

Annotations use a project namespace (`baq:`, e.g. `https://github.com/germanbraun/baqueano#`):

```turtle
@prefix sh:  <http://www.w3.org/ns/shacl#> .
@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .
@prefix baq: <https://github.com/germanbraun/baqueano#> .
@prefix schema: <https://schema.org/> .

<urn:baqueano:shape:Person> a sh:NodeShape ;
  sh:targetClass schema:Person ;
  baq:sampleSize 200 ;
  baq:sampleMethod "first-n" ;
  sh:property [
    sh:path schema:birthDate ;
    sh:datatype xsd:date ;
    sh:minCount 1 ;
    sh:maxCount 1 ;
    sh:severity sh:Info ;
    baq:support 0.97
  ] .
```

`shapes.ttl` is serialized with rdflib, to guarantee valid Turtle.

## Starter queries and diagram

Every generated query starts with a comment explaining what it does and which discovery data it came from, declares its PREFIXes and ends with `LIMIT 100`.

| File | What it queries |
|---|---|
| `00-overview.rq` | Classes with counts, and named graphs |
| `10-<class>-list.rq` | Instances of the class with their label (if a label property was detected) |
| `11-<class>-example.rq` | All properties of a real instance from the sample |
| `12-<class>-table.rq` | One row per instance, with the 5 to 8 highest-support properties as OPTIONAL |
| `20-<A>-to-<B>.rq` | Join along a discovered link, with labels on both sides |

Example `12-person-table.rq`:

```sparql
# People with their most frequent properties.
# Generated by Baqueano from a sample of 200 instances of schema:Person.
PREFIX schema: <https://schema.org/>

SELECT ?person ?name ?birthDate ?email WHERE {
  ?person a schema:Person .
  OPTIONAL { ?person schema:name ?name }           # support 1.00
  OPTIONAL { ?person schema:birthDate ?birthDate } # support 0.97
  OPTIONAL { ?person schema:email ?email }         # support 0.41
}
LIMIT 100
```

Queries are built from simple text templates, one function per query kind, not a generic builder. IRIs are written with a prefix when a known one exists, and in full between `<>` otherwise.

The `schema.mmd` diagram is a Mermaid `classDiagram`: each profiled class with its literal properties as attributes (with datatype), and each link as an arrow labelled with the property. It is capped at the 15 most populated classes and edges with support ≥ 0.05, so it stays readable.

## HTTP client

All traffic goes through a single `SparqlClient`, which never raises on network or endpoint errors: it returns a `QueryOutcome` with a status. Each step then picks its fallback with an `if`, without scattered `try/except` blocks.

```python
@dataclass
class QueryOutcome:
    step: str                  # "classes", "profile:schema:Person", ...
    query: str
    status: str                # "ok" | "timeout" | "http_error" | "parse_error" | "budget_exhausted"
    duration_s: float
    rows: list[dict] | None    # bindings, already simplified
    boolean: bool | None       # for ASK
    error: str | None
```

Rules:

- **Protocol:** POST with `application/x-www-form-urlencoded` (queries with `VALUES` can be long); on a 405 response, retry with GET. Request `application/sparql-results+json`.
- **Timeouts:** client-side timeout per query. A client timeout does not cancel the work on the server, which is why the pause between queries matters.
- **Budget:** a `Budget` object holds the total time; before every query the remaining time is checked and, if it is not enough, `budget_exhausted` is returned without sending anything.
- **Politeness:** a User-Agent identifying the tool and the repo, one query at a time, `--delay` between queries, and on 429 or 503 honour `Retry-After` with at most 2 retries.
- **Authentication:** headers from `--header` or `BAQUEANO_HEADER_*` environment variables. Never written to `queries.log` or `discovery.json`.
- **Log:** every query sent is appended to `queries.log` immediately, so there is a record even if the process is interrupted.

## Dependencies and repo layout

Python 3.10 or later, with three dependencies: **httpx** (fine control of timeouts and headers), **rdflib** (only to serialize `shapes.ttl` and read the Service Description) and **pytest** for development. The CLI uses argparse and JSON results are parsed by hand: no need for SPARQLWrapper.

```
baqueano/
  pyproject.toml
  README.md
  CLAUDE.md                  project conventions for Claude Code
  SPEC.md                    this guide
  baqueano/
    __init__.py
    __main__.py
    cli.py                   arguments, orchestration, exit codes
    client.py                SparqlClient, QueryOutcome, Budget, queries.log
    model.py                 discovery dataclasses (no I/O)
    scope.py                 GRAPH <iri> wrapping when --graph is set
    vocabularies.py          table of known vocabularies and prefixes
    steps/
      probe.py  void.py  shapes_found.py  graphs.py
      classes.py  vocab.py  profile.py  links.py
    generate/
      report.py  diagram.py  shapes.py  queries.py
  tests/
    fakes.py                 FakeClient with recorded responses
    test_profile.py  test_shapes.py  test_queries.py  ...
    integration/
      docker-compose.yml     Fuseki or Oxigraph with test data
      data/sample.ttl
```

Each step is a function `run(client, ctx) -> StepResult` and each generator a function `render(discovery) -> str`. Nothing else touches the network or the disk, so any step can be tested with a `FakeClient` and any output with a sample `discovery.json`.

## Testing and validation

Three levels, from fastest to most realistic.

1. **Unit tests, no network.** A `FakeClient` answers with recorded results per step. They cover: support and cardinality computation, shape thresholds, fallbacks (a timed-out count falls back to a sample), budget exhaustion, and that generated queries parse (with `rdflib.plugins.sparql.prepareQuery`).
2. **Integration with a real engine.** docker-compose starts Fuseki or Oxigraph with a known `sample.ttl`; the test runs `baqueano explore` and compares classes, properties and shapes with the expected ones.
3. **Manual validation against real endpoints**, staying polite (low budget, pauses):

| Endpoint | What it tests |
|---|---|
| Your endpoint | The real case that motivated the project |
| Wikidata | Huge size: timeouts and sample fallback |
| DBpedia | Many classes and its own ontology |
| UniProt | Scientific domain, may publish VoID |
| A small endpoint | That everything comes out exact and fast |

**v0 success criterion:** with the report in hand, write a useful query against an unknown endpoint in under 10 minutes.

## Implementation plan

Six milestones; each ends with green tests and something you can run.

1. **Skeleton and client.** `pyproject.toml`, `CLAUDE.md`, `model.py`, `client.py` with `QueryOutcome`, `Budget` and `queries.log`, `FakeClient`. Deliverable: `baqueano explore URL` runs the probe and writes the log.
2. **Cheap discovery.** VoID, existing shapes, graphs and classes steps, with their fallback. Deliverable: `discovery.json` with classes and graphs.
3. **Profile and links.** Vocabulary, per-class profile with batching, and links steps. The most delicate milestone: test the computations thoroughly with the `FakeClient`.
4. **Generators.** Shapes, queries and diagram, each reading only `discovery.json`. Check that the queries parse and that `shapes.ttl` is valid Turtle.
5. **Report and CLI polish.** `report.md`, exit codes, `--debug`, clear messages when the endpoint does not answer.
6. **Integration and real-world run.** docker-compose with test data, and a run against your endpoint and the public ones in the testing table.

## After v0

Roughly in order of value:

- `baqueano render discovery.json` to regenerate outputs without querying again.
- Validating the sample against the shapes (found or inferred), with a small data-quality report.
- Incoming properties and less biased sampling (e.g. random `OFFSET` when the count is known).
- Exporting the discovery as compact context for an LLM to write queries.
- sheXer as an alternative engine for shape inference.
- Browsable HTML report with the rendered diagram.
- A shared core with sparql-kata and the engine comparison tool (result normalization and comparison).

# Baqueano

A pathfinder for unknown SPARQL endpoints: point it at an endpoint and it
discovers which data and vocabularies sit behind it, on a time budget.

Status: milestone 5 of v0. `baqueano explore` runs the full discovery and
writes report.md, discovery.json, shapes.ttl, found-shapes.ttl, schema.mmd,
queries/*.rq and queries.log. See [SPEC.md](SPEC.md).

Since v0, `explore` also validates the sampled instances against the shapes
published in the endpoint and against its own inferred shapes (a SHACL Core
subset), in the "Data quality" section of report.md.

Exit codes: 0 complete, 1 complete with fallbacks or skipped steps,
2 endpoint unreachable, invalid arguments, or an unreadable discovery.json.

## Install (development)

```bash
python3 -m venv .venv
.venv/bin/pip install -e '.[dev]'
```

## Usage

```bash
.venv/bin/baqueano explore https://example.org/sparql --out ./baqueano-out
```

Choosing what gets profiled:

- `--class IRI` (repeatable) profiles these classes first. Full IRIs or known
  prefixes work, e.g. `--class schema:Person`. Otherwise classes go by size,
  and known infrastructure classes (value nodes, positions, image records)
  come last.
- `--class-property IRI` sets what links instances to classes (default
  `rdf:type`). Wikidata needs `wdt:P31`:

```bash
.venv/bin/baqueano explore https://query.wikidata.org/sparql --class-property wdt:P31 --class wd:Q5
```

When a class's size is known, its sample is taken as blocks at random
offsets. `--seed N` (default 1) makes the sample reproducible.

Credentials go in environment variables, not on the command line:

```bash
export BAQUEANO_HEADER_AUTHORIZATION="Bearer ..."
```

To regenerate the outputs from a saved discovery, without contacting any
endpoint (for example after upgrading Baqueano or changing a threshold):

```bash
.venv/bin/baqueano render ./baqueano-out/discovery.json
```

`render` rewrites report.md, shapes.ttl, schema.mmd, found-shapes.ttl and
queries/*.rq. It never touches discovery.json or queries.log. `--out DIR`
writes elsewhere; the default is the folder holding the JSON.

## Tests

Unit tests (no network):

```bash
.venv/bin/pytest
```

Integration tests against a real engine (Oxigraph in Docker, loaded with
`tests/integration/data/sample.trig`); they are skipped when it is not running:

```bash
docker compose -f tests/integration/docker-compose.yml up -d
.venv/bin/pytest tests/integration
docker compose -f tests/integration/docker-compose.yml down
```

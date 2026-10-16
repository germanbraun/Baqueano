# Baqueano

A pathfinder for unknown SPARQL endpoints: point it at an endpoint and it
discovers which data and vocabularies sit behind it, on a time budget.

Status: milestone 5 of v0. `baqueano explore` runs the full discovery and
writes report.md, discovery.json, shapes.ttl, found-shapes.ttl, schema.mmd,
queries/*.rq and queries.log. See [SPEC.md](SPEC.md).

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

# Baqueano

A pathfinder for unknown SPARQL endpoints: point it at an endpoint and it
discovers which data and vocabularies sit behind it, on a time budget.

Status: milestone 5 of v0. `baqueano explore` runs the full discovery and
writes report.md, discovery.json, shapes.ttl, found-shapes.ttl, schema.mmd,
queries/*.rq and queries.log. See [SPEC.md](SPEC.md).

Exit codes: 0 complete, 1 complete with fallbacks or skipped steps,
2 endpoint unreachable or invalid arguments.

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

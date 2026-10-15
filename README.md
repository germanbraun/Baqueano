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

```bash
.venv/bin/pytest
```

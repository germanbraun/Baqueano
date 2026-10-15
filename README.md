# Baqueano

A pathfinder for unknown SPARQL endpoints: point it at an endpoint and it
discovers which data and vocabularies sit behind it, on a time budget.

Status: milestone 1 of v0 (probe and query log). See [SPEC.md](SPEC.md).

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

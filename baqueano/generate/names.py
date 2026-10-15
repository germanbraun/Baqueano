"""Names derived from IRIs: file slugs, SPARQL variables, identifiers (pure)."""

from __future__ import annotations

import re

from baqueano.vocabularies import local_name


def slug(iri: str) -> str:
    """Local name lowercased and hyphenated: PostalAddress -> postal-address."""
    name = local_name(iri)
    name = re.sub(r"([a-z0-9])([A-Z])", r"\1-\2", name)
    name = re.sub(r"[^A-Za-z0-9]+", "-", name).strip("-").lower()
    return name or "class"


def identifier(iri: str) -> str:
    """Local name restricted to [A-Za-z0-9_], for variables and Mermaid ids."""
    name = re.sub(r"[^A-Za-z0-9_]", "_", local_name(iri)).strip("_")
    return name or "x"


def variable(iri: str) -> str:
    """SPARQL variable name for an IRI: schema:birthDate -> birthDate, schema:Person -> person."""
    name = identifier(iri)
    return name[0].lower() + name[1:]


def unique(names: list[str], separator: str = "-") -> list[str]:
    """Make names unique by appending 2, 3, ... to repeats, keeping order."""
    seen: dict[str, int] = {}
    taken = set(names)
    result = []
    for name in names:
        if name not in seen:
            seen[name] = 1
            result.append(name)
            continue
        n = seen[name]
        while True:
            n += 1
            candidate = f"{name}{separator}{n}"
            if candidate not in taken:
                break
        seen[name] = n
        taken.add(candidate)
        result.append(candidate)
    return result


def unique_map(iris: list[str], make, separator: str = "-") -> dict[str, str]:
    """{iri: unique name} for distinct IRIs, in order."""
    distinct = list(dict.fromkeys(iris))
    return dict(zip(distinct, unique([make(i) for i in distinct], separator)))

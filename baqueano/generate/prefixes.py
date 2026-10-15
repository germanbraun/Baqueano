"""Writing IRIs in generated SPARQL: prefixed when known, <full> otherwise."""

from __future__ import annotations

from baqueano.vocabularies import PREFIXES, shorten


class PrefixWriter:
    """Shortens IRIs and remembers which prefixes need a PREFIX line."""

    def __init__(self):
        self.used: set[str] = set()

    def iri(self, iri: str) -> str:
        short = shorten(iri)
        if not short.startswith("<"):
            self.used.add(short.split(":", 1)[0])
        return short

    def declarations(self) -> str:
        """PREFIX lines for every prefix used so far, sorted."""
        return "".join(f"PREFIX {p}: <{PREFIXES[p]}>\n" for p in sorted(self.used))

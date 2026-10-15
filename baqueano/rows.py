"""Reading values out of simplified result rows (see client.simplify_term)."""

from __future__ import annotations


def value(row: dict, var: str) -> str | None:
    """The lexical value of `var` in `row`, or None if unbound."""
    term = row.get(var)
    return term["value"] if term else None


def iri(row: dict, var: str) -> str | None:
    """The IRI bound to `var`, or None if unbound or not an IRI."""
    term = row.get(var)
    return term["value"] if term and term["type"] == "uri" else None


def node_id(row: dict, var: str) -> str | None:
    """IRI as-is, blank node as _:id. Fine for display, not for querying back."""
    term = row.get(var)
    if not term:
        return None
    return f"_:{term['value']}" if term["type"] == "bnode" else term["value"]


def int_value(row: dict, var: str) -> int | None:
    """`var` as an int (COUNT results, void:triples, ...), or None."""
    text = value(row, var)
    if text is None:
        return None
    try:
        return int(text)
    except ValueError:
        try:
            return int(float(text))   # some engines answer "1.2E3" for large counts
        except ValueError:
            return None

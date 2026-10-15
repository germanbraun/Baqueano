"""FakeClient: answers steps with recorded outcomes, without any network.

Usage:

    client = FakeClient({
        "probe": ask(True),
        "classes": [timeout(), select([{"class": iri("http://ex/A")}])],
    })

A list is consumed in order (the last entry repeats). Asking for a step that
has no recorded response fails the test loudly instead of hiding a fallback.
"""

from __future__ import annotations

from baqueano.client import DocumentOutcome, QueryOutcome


# -- term helpers (same shape as client.simplify_term) ----------------------

def iri(value: str) -> dict:
    return {"type": "uri", "value": value}


def lit(value: str, datatype: str | None = None, lang: str | None = None) -> dict:
    term = {"type": "literal", "value": value}
    if datatype:
        term["datatype"] = datatype
    if lang:
        term["lang"] = lang
    return term


def bnode(value: str) -> dict:
    return {"type": "bnode", "value": value}


# -- outcome helpers ---------------------------------------------------------
# step and query are filled in by FakeClient when the response is served.

def select(rows: list[dict]) -> QueryOutcome:
    return QueryOutcome(step="", query="", status="ok", duration_s=0.0, rows=rows, boolean=None, error=None)


def ask(value: bool) -> QueryOutcome:
    return QueryOutcome(step="", query="", status="ok", duration_s=0.0, rows=None, boolean=value, error=None)


def rdf(text: str, content_type: str = "text/turtle") -> QueryOutcome:
    """A CONSTRUCT answer."""
    return QueryOutcome(step="", query="", status="ok", duration_s=0.0, rows=None, boolean=None, error=None,
                        text=text, content_type=content_type)


def failed(status: str, error: str | None = None) -> QueryOutcome:
    return QueryOutcome(step="", query="", status=status, duration_s=0.0, rows=None, boolean=None,
                        error=error or status)


def timeout() -> QueryOutcome:
    return failed("timeout", "no answer after 30.0s")


def http_error(code: int | None = 500) -> QueryOutcome:
    """code=None means a connection failure (no HTTP response)."""
    outcome = failed("http_error", f"HTTP {code}" if code else "ConnectError: refused")
    outcome.http_status = code
    return outcome


def budget_exhausted() -> QueryOutcome:
    return failed("budget_exhausted", "budget exhausted")


def document(text: str | None = None, content_type: str | None = "text/turtle", status: str = "ok",
             server: str | None = None) -> DocumentOutcome:
    return DocumentOutcome(step="", status=status, duration_s=0.0, content_type=content_type, text=text,
                           server_header=server, error=None if status == "ok" else status)


# -- the fake ----------------------------------------------------------------

class FakeClient:
    def __init__(self, responses: dict[str, object]):
        self._responses = {step: list(r) if isinstance(r, list) else [r] for step, r in responses.items()}
        self.calls: list[tuple[str, str]] = []   # (step, query or accept)

    def _next(self, step: str):
        if step not in self._responses:
            raise AssertionError(f"FakeClient: no recorded response for step {step!r}")
        queue = self._responses[step]
        return queue.pop(0) if len(queue) > 1 else queue[0]

    def query(self, step: str, query: str) -> QueryOutcome:
        self.calls.append((step, query))
        recorded = self._next(step)
        return QueryOutcome(step=step, query=query, status=recorded.status, duration_s=recorded.duration_s,
                            rows=recorded.rows, boolean=recorded.boolean, error=recorded.error,
                            http_status=recorded.http_status, text=recorded.text,
                            content_type=recorded.content_type)

    def construct(self, step: str, query: str) -> QueryOutcome:
        return self.query(step, query)

    def get_document(self, step: str, accept: str) -> DocumentOutcome:
        self.calls.append((step, accept))
        recorded = self._next(step)
        return DocumentOutcome(step=step, status=recorded.status, duration_s=recorded.duration_s,
                               content_type=recorded.content_type, text=recorded.text,
                               server_header=recorded.server_header, error=recorded.error)

    def queries_for(self, step: str) -> list[str]:
        return [q for s, q in self.calls if s == step]

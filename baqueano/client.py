"""The only module that talks to the network.

SparqlClient never raises on network or endpoint errors: every call returns
an outcome with a status, and the caller picks its fallback with an `if`.

Statuses of QueryOutcome / DocumentOutcome:
    ok                the endpoint answered and the response was understood
    timeout           no answer within the per-query timeout
    http_error        connection failure or a 4xx/5xx response
    parse_error       the response was not valid SPARQL JSON results
    budget_exhausted  not enough total time left; nothing was sent

Queries are reported to an optional `log` callback as one dict per query
(the CLI writes them to queries.log). Request headers are never logged.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Callable

import httpx

from baqueano import DEFAULT_USER_AGENT

logger = logging.getLogger(__name__)

SPARQL_JSON = "application/sparql-results+json"
RDF_ACCEPT = "text/turtle, application/n-triples;q=0.9, application/rdf+xml;q=0.5"

MIN_QUERY_SECONDS = 1.0      # don't start a query with less budget than this
MAX_RETRIES = 2              # retries on RETRY_STATUSES
RETRY_STATUSES = (429, 502, 503)  # rate limit, transient gateway error, busy
DEFAULT_RETRY_AFTER_S = 5.0  # when 429/503 comes without a usable Retry-After
MAX_RETRY_AFTER_S = 60.0     # never wait longer than this for one retry
ERROR_BODY_CHARS = 300       # how much of an error response to keep


class Budget:
    """Total time allowed for the whole discovery."""

    def __init__(self, total_s: float, clock: Callable[[], float] = time.monotonic):
        self.total_s = total_s
        self._clock = clock
        self._start = clock()

    def elapsed(self) -> float:
        return self._clock() - self._start

    def remaining(self) -> float:
        return max(0.0, self.total_s - self.elapsed())


@dataclass
class QueryOutcome:
    step: str                  # "classes", "profile:schema:Person", ...
    query: str
    status: str                # ok | timeout | http_error | parse_error | budget_exhausted
    duration_s: float
    rows: list[dict] | None    # bindings, already simplified (see simplify_term)
    boolean: bool | None       # for ASK
    error: str | None
    http_status: int | None = None
    text: str | None = None          # for CONSTRUCT: the RDF as returned
    content_type: str | None = None  # for CONSTRUCT: to pick the RDF parser


@dataclass
class DocumentOutcome:
    """Result of a plain GET on the endpoint (used for the Service Description)."""
    step: str
    status: str                # same statuses as QueryOutcome (except parse_error)
    duration_s: float
    content_type: str | None
    text: str | None
    server_header: str | None
    error: str | None
    http_status: int | None = None


@dataclass
class _Response:
    """What _send returns: a response when status == "ok", otherwise an error."""
    status: str
    response: httpx.Response | None
    error: str | None
    method: str | None         # method actually used, None if nothing was sent
    http_status: int | None


# ---------------------------------------------------------------------------
# Pure helpers (no network): easy to test on their own.

def simplify_term(term: dict) -> dict:
    """SPARQL JSON term -> {"type", "value", optional "datatype", optional "lang"}.

    type is "uri", "literal" or "bnode" ("typed-literal" from old engines is
    folded into "literal").
    """
    kind = term.get("type")
    if kind == "typed-literal":
        kind = "literal"
    out = {"type": kind, "value": term.get("value")}
    if "datatype" in term:
        out["datatype"] = term["datatype"]
    if "xml:lang" in term:
        out["lang"] = term["xml:lang"]
    return out


def parse_sparql_json(text: str) -> tuple[list[dict] | None, bool | None]:
    """Parse SPARQL 1.1 JSON results into (rows, boolean).

    SELECT gives (rows, None); ASK gives (None, boolean).
    Raises ValueError when the text is not SPARQL JSON results.
    """
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        raise ValueError(f"not JSON: {e}") from e
    if not isinstance(data, dict):
        raise ValueError("JSON results must be an object")
    if "boolean" in data:
        if not isinstance(data["boolean"], bool):
            raise ValueError("'boolean' is not true/false")
        return None, data["boolean"]
    bindings = data.get("results", {}).get("bindings") if isinstance(data.get("results"), dict) else None
    if not isinstance(bindings, list):
        raise ValueError("no 'results.bindings' and no 'boolean' in the response")
    rows = [{var: simplify_term(term) for var, term in b.items()} for b in bindings]
    return rows, None


def parse_retry_after(value: str | None, now: datetime | None = None) -> float:
    """Seconds to wait from a Retry-After header (seconds or HTTP date)."""
    if not value:
        return DEFAULT_RETRY_AFTER_S
    value = value.strip()
    if value.isdigit():
        return min(float(value), MAX_RETRY_AFTER_S)
    try:
        when = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return DEFAULT_RETRY_AFTER_S
    now = now or datetime.now(timezone.utc)
    return min(max(0.0, (when - now).total_seconds()), MAX_RETRY_AFTER_S)


# ---------------------------------------------------------------------------

class SparqlClient:
    def __init__(
        self,
        endpoint: str,
        *,
        budget: Budget,
        timeout_s: float = 30.0,
        delay_s: float = 0.5,
        headers: dict[str, str] | None = None,
        user_agent: str = DEFAULT_USER_AGENT,
        log: Callable[[dict], None] | None = None,
        transport: httpx.BaseTransport | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ):
        self.endpoint = endpoint
        self.budget = budget
        self.timeout_s = timeout_s
        self.delay_s = delay_s
        self._log = log
        self._sleep = sleep
        self._sent_any = False
        all_headers = {"User-Agent": user_agent, **(headers or {})}
        self._http = httpx.Client(headers=all_headers, transport=transport, follow_redirects=True)

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> SparqlClient:
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    # -- public API ---------------------------------------------------------

    def query(self, step: str, query: str) -> QueryOutcome:
        """Run a SELECT or ASK query and return its parsed results."""
        return self._query(step, query, construct=False)

    def construct(self, step: str, query: str) -> QueryOutcome:
        """Run a CONSTRUCT query; the RDF comes back unparsed in .text."""
        return self._query(step, query, construct=True)

    def _query(self, step: str, query: str, construct: bool) -> QueryOutcome:
        kind = "construct" if construct else "query"
        started = time.perf_counter()
        try:
            sent = self._send(form={"query": query}, accept=RDF_ACCEPT if construct else SPARQL_JSON)
        except KeyboardInterrupt:
            self._write_log(step, kind, query, "interrupted", time.perf_counter() - started,
                            None, "POST", None, "interrupted by user")
            raise
        duration = round(time.perf_counter() - started, 3)

        outcome = QueryOutcome(step=step, query=query, status=sent.status, duration_s=duration,
                               rows=None, boolean=None, error=sent.error, http_status=sent.http_status)
        if sent.status == "ok" and construct:
            outcome.text = sent.response.text
            outcome.content_type = sent.response.headers.get("content-type")
        elif sent.status == "ok":
            try:
                outcome.rows, outcome.boolean = parse_sparql_json(sent.response.text)
            except ValueError as e:
                outcome.status, outcome.error = "parse_error", str(e)

        n_rows = len(outcome.rows) if outcome.rows is not None else None
        self._write_log(step, kind, query, outcome.status, duration, n_rows, sent.method,
                        sent.http_status, outcome.error)
        return outcome

    def get_document(self, step: str, accept: str, timeout_s: float | None = None) -> DocumentOutcome:
        """GET the endpoint URL without a query (e.g. for its Service Description).
        timeout_s, when given, replaces the per-query timeout if it is shorter."""
        started = time.perf_counter()
        sent = self._send(form=None, accept=accept, timeout_s=timeout_s)
        duration = round(time.perf_counter() - started, 3)
        resp = sent.response
        outcome = DocumentOutcome(
            step=step,
            status=sent.status,
            duration_s=duration,
            content_type=resp.headers.get("content-type") if resp is not None else None,
            text=resp.text if resp is not None and sent.status == "ok" else None,
            server_header=resp.headers.get("server") if resp is not None else None,
            error=sent.error,
            http_status=sent.http_status,
        )
        self._write_log(step, "document", f"GET {self.endpoint} (Accept: {accept})", sent.status,
                        duration, None, sent.method, sent.http_status, sent.error)
        return outcome

    # -- internals ----------------------------------------------------------

    def _send(self, form: dict | None, accept: str, timeout_s: float | None = None) -> _Response:
        """One logical request: budget check, pause, 405 -> GET, 429/503 retries.

        form=None means a plain GET of the endpoint.
        """
        if self.budget.remaining() < MIN_QUERY_SECONDS:
            return self._budget_exhausted()
        if self._sent_any and self.delay_s > 0:
            self._sleep(self.delay_s)
        if self.budget.remaining() < MIN_QUERY_SECONDS:
            return self._budget_exhausted()

        method = "POST" if form is not None else "GET"
        retries = 0
        while True:
            timeout = min(self.timeout_s, timeout_s or self.timeout_s, self.budget.remaining())
            self._sent_any = True
            try:
                if method == "POST":
                    resp = self._http.post(self.endpoint, data=form, headers={"Accept": accept},
                                           timeout=timeout)
                else:
                    resp = self._http.get(self.endpoint, params=form, headers={"Accept": accept},
                                          timeout=timeout)
            except httpx.TimeoutException:
                return _Response("timeout", None, f"no answer after {timeout:.1f}s", method, None)
            except httpx.HTTPError as e:
                return _Response("http_error", None, f"{type(e).__name__}: {e}", method, None)

            code = resp.status_code
            if code == 405 and method == "POST" and form is not None:
                logger.debug("POST not allowed (405), retrying with GET")
                method = "GET"
                continue

            if code in RETRY_STATUSES and retries < MAX_RETRIES:
                wait = parse_retry_after(resp.headers.get("retry-after"))
                if wait + MIN_QUERY_SECONDS > self.budget.remaining():
                    return _Response("http_error", resp, f"HTTP {code}; Retry-After {wait:.0f}s exceeds budget",
                                     method, code)
                retries += 1
                logger.debug("HTTP %s, waiting %.1fs before retry %d/%d", code, wait, retries, MAX_RETRIES)
                self._sleep(wait)
                continue

            if code >= 400:
                body = " ".join(resp.text.split())[:ERROR_BODY_CHARS]   # one line: engines send stack traces
                return _Response("http_error", resp, f"HTTP {code}: {body}", method, code)

            return _Response("ok", resp, None, method, code)

    def _budget_exhausted(self) -> _Response:
        logger.debug("budget exhausted (%.1fs left), not sending", self.budget.remaining())
        return _Response("budget_exhausted", None, "budget exhausted", None, None)

    def _write_log(self, step, kind, query, status, duration_s, rows, method, http_status, error) -> None:
        logger.debug("[%s] %s -> %s in %.2fs (rows: %s)%s", step, kind, status, duration_s, rows,
                     f" {error}" if error else "")
        if self._log is None:
            return
        self._log({
            "time": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "step": step,
            "kind": kind,
            "method": method,
            "status": status,
            "http_status": http_status,
            "duration_s": duration_s,
            "rows": rows,
            "error": error,
            "query": query,
        })

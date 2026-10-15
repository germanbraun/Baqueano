import json
from datetime import datetime, timezone
from urllib.parse import parse_qs

import httpx
import pytest

from baqueano.client import (
    DEFAULT_RETRY_AFTER_S,
    MAX_RETRY_AFTER_S,
    Budget,
    SparqlClient,
    parse_retry_after,
    parse_sparql_json,
    simplify_term,
)

ENDPOINT = "http://example.org/sparql"

SELECT_JSON = {
    "head": {"vars": ["s", "label"]},
    "results": {"bindings": [
        {"s": {"type": "uri", "value": "http://ex/a"},
         "label": {"type": "literal", "value": "A", "xml:lang": "en"}},
        {"s": {"type": "bnode", "value": "b0"}},
    ]},
}


class FakeClock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


def make_client(handler, budget_s=300.0, clock=None, **kwargs):
    log, sleeps = [], []
    clock = clock or FakeClock()
    budget = Budget(budget_s, clock=clock)
    client = SparqlClient(ENDPOINT, budget=budget, transport=httpx.MockTransport(handler),
                          log=log.append, sleep=sleeps.append, **kwargs)
    return client, log, sleeps


def json_response(data, status=200):
    return httpx.Response(status, json=data, headers={"content-type": "application/sparql-results+json"})


# -- pure helpers --------------------------------------------------------------

def test_simplify_term_keeps_datatype_and_lang():
    assert simplify_term({"type": "typed-literal", "value": "1", "datatype": "xsd:int"}) == \
        {"type": "literal", "value": "1", "datatype": "xsd:int"}
    assert simplify_term({"type": "literal", "value": "hi", "xml:lang": "en"}) == \
        {"type": "literal", "value": "hi", "lang": "en"}


def test_parse_select_and_ask():
    rows, boolean = parse_sparql_json(json.dumps(SELECT_JSON))
    assert boolean is None
    assert rows[0]["label"] == {"type": "literal", "value": "A", "lang": "en"}
    assert rows[1] == {"s": {"type": "bnode", "value": "b0"}}
    assert parse_sparql_json('{"head": {}, "boolean": true}') == (None, True)


@pytest.mark.parametrize("text", ["<html>", "[]", '{"head": {}}', '{"boolean": "yes"}'])
def test_parse_rejects_non_results(text):
    with pytest.raises(ValueError):
        parse_sparql_json(text)


def test_parse_retry_after():
    assert parse_retry_after("7") == 7.0
    assert parse_retry_after(None) == DEFAULT_RETRY_AFTER_S
    assert parse_retry_after("soon") == DEFAULT_RETRY_AFTER_S
    assert parse_retry_after("100000") == MAX_RETRY_AFTER_S
    now = datetime(2026, 10, 15, 12, 0, 0, tzinfo=timezone.utc)
    assert parse_retry_after("Thu, 15 Oct 2026 12:00:10 GMT", now=now) == 10.0


def test_budget_remaining():
    clock = FakeClock()
    budget = Budget(10, clock=clock)
    clock.now = 4
    assert budget.remaining() == 6
    clock.now = 20
    assert budget.remaining() == 0


# -- requests ------------------------------------------------------------------

def test_select_posts_form_and_parses_rows():
    seen = {}

    def handler(request):
        seen["method"] = request.method
        seen["content_type"] = request.headers["content-type"]
        seen["accept"] = request.headers["accept"]
        seen["query"] = parse_qs(request.content.decode())["query"][0]
        return json_response(SELECT_JSON)

    client, log, _ = make_client(handler)
    outcome = client.query("classes", "SELECT * WHERE { ?s ?p ?o }")
    assert outcome.status == "ok"
    assert len(outcome.rows) == 2
    assert seen == {"method": "POST", "content_type": "application/x-www-form-urlencoded",
                    "accept": "application/sparql-results+json", "query": "SELECT * WHERE { ?s ?p ?o }"}
    assert log[0]["step"] == "classes"
    assert log[0]["rows"] == 2
    assert log[0]["query"] == "SELECT * WHERE { ?s ?p ?o }"


def test_ask_returns_boolean():
    client, _, _ = make_client(lambda r: json_response({"head": {}, "boolean": False}))
    outcome = client.query("probe", "ASK { ?s ?p ?o }")
    assert outcome.status == "ok"
    assert outcome.boolean is False
    assert outcome.rows is None


def test_405_retries_with_get():
    methods = []

    def handler(request):
        methods.append(request.method)
        if request.method == "POST":
            return httpx.Response(405)
        assert request.url.params["query"] == "ASK {}"
        return json_response({"boolean": True})

    client, log, _ = make_client(handler)
    outcome = client.query("probe", "ASK {}")
    assert outcome.status == "ok"
    assert methods == ["POST", "GET"]
    assert log[0]["method"] == "GET"


def test_timeout_is_a_status():
    def handler(request):
        raise httpx.ReadTimeout("slow", request=request)

    client, log, _ = make_client(handler)
    outcome = client.query("classes", "SELECT ...")
    assert outcome.status == "timeout"
    assert outcome.rows is None
    assert log[0]["status"] == "timeout"


def test_connection_error_is_http_error():
    def handler(request):
        raise httpx.ConnectError("refused", request=request)

    client, _, _ = make_client(handler)
    outcome = client.query("probe", "ASK {}")
    assert outcome.status == "http_error"
    assert "refused" in outcome.error


def test_server_error_keeps_body_snippet():
    client, _, _ = make_client(lambda r: httpx.Response(500, text="Query parse error"))
    outcome = client.query("classes", "SELECT ...")
    assert outcome.status == "http_error"
    assert outcome.http_status == 500
    assert "Query parse error" in outcome.error


def test_html_answer_is_parse_error():
    client, _, _ = make_client(lambda r: httpx.Response(200, text="<html>login</html>"))
    assert client.query("classes", "SELECT ...").status == "parse_error"


def test_429_honours_retry_after_then_succeeds():
    responses = iter([httpx.Response(429, headers={"retry-after": "3"}), json_response({"boolean": True})])
    client, _, sleeps = make_client(lambda r: next(responses), delay_s=0)
    assert client.query("probe", "ASK {}").status == "ok"
    assert sleeps == [3.0]


def test_503_gives_up_after_two_retries():
    calls = []

    def handler(request):
        calls.append(1)
        return httpx.Response(503, headers={"retry-after": "1"})

    client, _, sleeps = make_client(handler, delay_s=0)
    outcome = client.query("probe", "ASK {}")
    assert outcome.status == "http_error"
    assert len(calls) == 3
    assert sleeps == [1.0, 1.0]


def test_retry_after_longer_than_budget_is_not_waited():
    client, _, sleeps = make_client(lambda r: httpx.Response(429, headers={"retry-after": "30"}),
                                    budget_s=10, delay_s=0)
    outcome = client.query("probe", "ASK {}")
    assert outcome.status == "http_error"
    assert "exceeds budget" in outcome.error
    assert sleeps == []


def test_budget_exhausted_sends_nothing():
    clock = FakeClock()
    sent = []

    def handler(request):
        sent.append(1)
        return json_response({"boolean": True})

    client, log, _ = make_client(handler, budget_s=10, clock=clock)
    clock.now = 9.5
    outcome = client.query("classes", "SELECT ...")
    assert outcome.status == "budget_exhausted"
    assert sent == []
    assert log[0]["status"] == "budget_exhausted"
    assert log[0]["method"] is None


def test_timeout_is_capped_by_remaining_budget():
    clock = FakeClock()
    seen = {}

    def handler(request):
        seen["timeout"] = request.extensions["timeout"]["read"]
        return json_response({"boolean": True})

    client, _, _ = make_client(handler, budget_s=100, clock=clock, timeout_s=30)
    clock.now = 95
    client.query("probe", "ASK {}")
    assert seen["timeout"] == 5


def test_delay_between_queries_but_not_before_first():
    client, _, sleeps = make_client(lambda r: json_response({"boolean": True}), delay_s=0.5)
    client.query("a", "ASK {}")
    assert sleeps == []
    client.query("b", "ASK {}")
    client.query("c", "ASK {}")
    assert sleeps == [0.5, 0.5]


def test_headers_are_sent_but_never_logged():
    seen = {}

    def handler(request):
        seen.update(request.headers)
        return json_response({"boolean": True})

    client, log, _ = make_client(handler, headers={"Authorization": "Bearer s3cret"}, user_agent="test-agent")
    client.query("probe", "ASK {}")
    assert seen["authorization"] == "Bearer s3cret"
    assert seen["user-agent"] == "test-agent"
    assert "s3cret" not in json.dumps(log)


def test_get_document_returns_text_and_server():
    def handler(request):
        assert request.method == "GET"
        assert request.headers["accept"] == "text/turtle"
        assert "query" not in request.url.params
        return httpx.Response(200, text="@prefix x: <http://x/> .",
                              headers={"content-type": "text/turtle", "server": "Fuseki"})

    client, log, _ = make_client(handler)
    doc = client.get_document("probe:service-description", "text/turtle")
    assert doc.status == "ok"
    assert doc.server_header == "Fuseki"
    assert doc.content_type == "text/turtle"
    assert doc.text.startswith("@prefix")
    assert log[0]["kind"] == "document"


def test_get_document_error_still_reports_server():
    client, _, _ = make_client(lambda r: httpx.Response(400, text="no query", headers={"server": "Virtuoso"}))
    doc = client.get_document("probe:service-description", "text/turtle")
    assert doc.status == "http_error"
    assert doc.server_header == "Virtuoso"
    assert doc.text is None

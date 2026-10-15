from baqueano.context import Context, Settings
from baqueano.model import Discovery
from baqueano.steps import probe
from tests.fakes import FakeClient, ask, budget_exhausted, document, http_error, timeout

SD_TURTLE = """
@prefix sd: <http://www.w3.org/ns/sparql-service-description#> .
<http://example.org/sparql#service> a sd:Service ;
    sd:endpoint <http://example.org/sparql> .
"""


def make_ctx(graph=None):
    return Context(Discovery(endpoint="http://example.org/sparql", started_at="now"), Settings(graph=graph))


def test_ok_with_service_description():
    client = FakeClient({"probe": ask(True),
                         probe.SD_STEP: document(SD_TURTLE, "text/turtle; charset=utf-8", server="Fuseki")})
    ctx = make_ctx()
    result = probe.run(client, ctx)
    assert result.status == "ok"
    assert ctx.discovery.has_service_description is True
    assert ctx.discovery.server_header == "Fuseki"
    assert client.queries_for("probe") == ["ASK { ?s ?p ?o }"]


def test_ok_without_service_description():
    client = FakeClient({"probe": ask(True), probe.SD_STEP: document("<html>query form</html>", "text/html")})
    ctx = make_ctx()
    result = probe.run(client, ctx)
    assert result.status == "ok"
    assert ctx.discovery.has_service_description is False
    assert "no service description" in result.message


def test_service_description_fetch_failure_is_not_fatal():
    client = FakeClient({"probe": ask(True), probe.SD_STEP: document(status="http_error", server="nginx")})
    ctx = make_ctx()
    assert probe.run(client, ctx).status == "ok"
    assert ctx.discovery.server_header == "nginx"


def test_empty_endpoint_is_reported():
    client = FakeClient({"probe": ask(False), probe.SD_STEP: document(status="http_error")})
    result = probe.run(client, make_ctx())
    assert result.status == "ok"
    assert "no triples" in result.message


def test_graph_scope_wraps_ask():
    client = FakeClient({"probe": ask(True), probe.SD_STEP: document(status="http_error")})
    probe.run(client, make_ctx(graph="http://ex/g"))
    assert client.queries_for("probe") == ["ASK { GRAPH <http://ex/g> { ?s ?p ?o } }"]


def test_unreachable_endpoint():
    client = FakeClient({"probe": http_error(502)})
    result = probe.run(client, make_ctx())
    assert result.status == "error"
    assert "HTTP 502" in result.message
    assert client.queries_for(probe.SD_STEP) == []   # no point fetching the description


def test_timeout_and_budget_map_to_step_statuses():
    assert probe.run(FakeClient({"probe": timeout()}), make_ctx()).status == "timeout"
    assert probe.run(FakeClient({"probe": budget_exhausted()}), make_ctx()).status == "skipped"


def test_has_service_description_needs_sd_service():
    assert probe.has_service_description(SD_TURTLE, "text/turtle")
    assert not probe.has_service_description("<http://a> <http://b> <http://c> .", "text/turtle")
    assert not probe.has_service_description("this is not turtle {", "text/turtle")
    assert not probe.has_service_description(SD_TURTLE, "text/html")


def test_failure_hints():
    assert "authentication" in probe.failure_hint("http_error", 401)
    assert "authentication" in probe.failure_hint("http_error", 403)
    assert "endpoint path" in probe.failure_hint("http_error", 404)
    assert "down or overloaded" in probe.failure_hint("http_error", 503)
    assert "could not connect" in probe.failure_hint("http_error", None)
    assert "--timeout" in probe.failure_hint("timeout", None)
    assert "not with SPARQL results" in probe.failure_hint("parse_error", 200)


def test_failure_message_includes_hint():
    result = probe.run(FakeClient({"probe": http_error(401)}), make_ctx())
    assert result.message.startswith("endpoint did not answer: HTTP 401 -> ")
    assert "BAQUEANO_HEADER_AUTHORIZATION" in result.message

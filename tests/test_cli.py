import json

import pytest

from baqueano import cli, model
from baqueano.context import Context, Settings
from baqueano.model import Discovery, StepResult, discovery_from_dict, discovery_to_dict
from baqueano.steps import probe
from tests.fakes import FakeClient, ask, document, http_error


def make_ctx():
    return Context(Discovery(endpoint="http://example.org/sparql", started_at="now"), Settings())


def test_parse_header():
    assert cli.parse_header("Authorization: Bearer a:b") == ("Authorization", "Bearer a:b")
    with pytest.raises(ValueError):
        cli.parse_header("no colon")
    with pytest.raises(ValueError):
        cli.parse_header(": value")


def test_headers_from_env():
    env = {"BAQUEANO_HEADER_AUTHORIZATION": "Bearer x", "BAQUEANO_HEADER_X_API_KEY": "k",
           "BAQUEANO_HEADER_": "ignored", "PATH": "/bin"}
    assert cli.headers_from_env(env) == {"Authorization": "Bearer x", "X-Api-Key": "k"}


def test_exit_codes():
    ok = StepResult(probe.NAME, model.OK)
    assert cli.exit_code([ok]) == cli.EXIT_OK
    assert cli.exit_code([ok, StepResult("classes", model.SAMPLED)]) == cli.EXIT_DEGRADED
    assert cli.exit_code([ok, StepResult("void", model.UNSUPPORTED)]) == cli.EXIT_OK
    assert cli.exit_code([StepResult(probe.NAME, model.ERROR, "down")]) == cli.EXIT_ERROR
    assert cli.exit_code([]) == cli.EXIT_ERROR


def test_failed_probe_stops_the_pipeline():
    ran = []
    steps = [(probe.NAME, probe.run), ("later", lambda client, ctx: ran.append(1))]
    ctx = make_ctx()
    cli.run_steps(FakeClient({"probe": http_error()}), ctx, steps)
    assert [s.name for s in ctx.discovery.steps] == ["probe"]
    assert ran == []


def test_crashing_step_is_recorded_and_pipeline_continues():
    def boom(client, ctx):
        raise RuntimeError("bug")

    steps = [(probe.NAME, probe.run), ("boom", boom),
             ("after", lambda client, ctx: StepResult("after", model.OK))]
    client = FakeClient({"probe": ask(True), probe.SD_STEP: document(status="http_error")})
    ctx = make_ctx()
    cli.run_steps(client, ctx, steps)
    assert [(s.name, s.status) for s in ctx.discovery.steps] == \
        [("probe", "ok"), ("boom", "error"), ("after", "ok")]


@pytest.mark.parametrize("argv", [
    ["explore", "ftp://x"],
    ["explore", "http://x", "--class", "unknownprefix:Thing"],
    ["explore", "http://x", "--class-property", "not an iri"],
    ["explore", "http://x", "--budget", "0"],
    ["explore", "http://x", "--header", "nonsense"],
])
def test_invalid_arguments_exit_2(argv):
    with pytest.raises(SystemExit) as e:
        cli.main(argv)
    assert e.value.code == 2


def test_discovery_roundtrip():
    d = Discovery(endpoint="http://e", started_at="t", steps=[StepResult("probe", "ok", "fine")],
                  classes=[model.ClassInfo("http://ex/A", 3, True)],
                  profiles=[model.ClassProfile("http://ex/A", 3, "first-n", False, "http://ex/a1",
                                               [model.PropertyProfile("http://ex/p", 1.0, 1, 0, 3)])],
                  links=[model.Link("http://ex/A", "http://ex/p", "http://ex/B", 0.5)])
    data = json.loads(json.dumps(discovery_to_dict(d)))
    assert discovery_from_dict(data) == d


def test_explore_unreachable_endpoint_writes_outputs(tmp_path, monkeypatch):
    # Port 9 (discard) on localhost: connection refused, no real network.
    out = tmp_path / "out"
    code = cli.main(["explore", "http://127.0.0.1:9/sparql", "--out", str(out), "--delay", "0",
                     "--timeout", "2", "--budget", "10"])
    assert code == cli.EXIT_ERROR
    log_lines = (out / "queries.log").read_text().splitlines()
    assert json.loads(log_lines[0])["status"] == "http_error"
    discovery = json.loads((out / "discovery.json").read_text())
    assert discovery["steps"][0]["status"] == "error"
    assert "could not connect" in discovery["steps"][0]["message"]
    report = (out / "report.md").read_text()            # outputs are written even when nothing answered
    assert "**probe** (error)" in report
    assert (out / "queries" / "00-overview.rq").exists()


def files_under(folder):
    return {p.relative_to(folder).as_posix(): p.read_bytes() for p in sorted(folder.rglob("*")) if p.is_file()}


def test_render_matches_write_outputs(tmp_path):
    from tests.sample_discovery import sample_discovery

    discovery = sample_discovery()
    discovery.found_shapes_ttl = "@prefix sh: <http://www.w3.org/ns/shacl#> .\n"
    explored = tmp_path / "explored"
    explored.mkdir()
    cli.write_outputs(explored, discovery)
    json_bytes = (explored / "discovery.json").read_bytes()

    rendered = tmp_path / "rendered"
    code = cli.main(["render", str(explored / "discovery.json"), "--out", str(rendered)])
    assert code == cli.EXIT_OK
    expected = files_under(explored)
    del expected["discovery.json"]                       # render never writes discovery.json
    assert files_under(rendered) == expected
    assert "found-shapes.ttl" in expected and "queries/00-overview.rq" in expected

    # Default --out is the JSON's folder; discovery.json is left untouched.
    (explored / "report.md").unlink()
    assert cli.main(["render", str(explored / "discovery.json")]) == cli.EXIT_OK
    assert (explored / "discovery.json").read_bytes() == json_bytes
    assert files_under(explored) == {**expected, "discovery.json": json_bytes}


@pytest.mark.parametrize("content", ["{not json", "[1, 2]", '{"endpoint": "x", "nonsense": 1}'])
def test_render_invalid_json_exits_2(tmp_path, capsys, content):
    path = tmp_path / "discovery.json"
    path.write_text(content)
    assert cli.main(["render", str(path)]) == cli.EXIT_ERROR
    err = capsys.readouterr().err.strip()
    assert err.startswith("baqueano: ") and "\n" not in err
    assert not (tmp_path / "report.md").exists()


def test_render_missing_file_exits_2(tmp_path, capsys):
    assert cli.main(["render", str(tmp_path / "nope.json")]) == cli.EXIT_ERROR
    assert "cannot read" in capsys.readouterr().err

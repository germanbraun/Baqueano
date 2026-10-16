"""Command line: arguments, orchestration, exit codes. The only module that writes files.

Exit codes:
    0  discovery complete
    1  complete with degraded or skipped steps
    2  error (endpoint unreachable, invalid arguments, unreadable discovery.json)
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from baqueano import DEFAULT_USER_AGENT, __version__, model
from baqueano.client import Budget, SparqlClient
from baqueano.context import Context, Settings
from baqueano.generate import diagram
from baqueano.generate import queries as queries_gen
from baqueano.generate import report
from baqueano.generate import shapes as shapes_gen
from baqueano.model import Discovery, StepResult, discovery_to_dict
from baqueano.vocabularies import expand
from baqueano.steps import classes, graphs, links, namespaces, probe, profile, shapes_found, vocab, void
from baqueano.steps import validate as validate_step   # cli.validate() checks arguments

logger = logging.getLogger("baqueano")

EXIT_OK = 0
EXIT_DEGRADED = 1
EXIT_ERROR = 2

# Step statuses that do not make a run "degraded" (exit code 1).
COMPLETE_STATUSES = {model.OK, model.UNSUPPORTED}

ENV_HEADER_PREFIX = "BAQUEANO_HEADER_"

# Pipeline order, cheapest first. The last three steps send no queries, so
# they still run when the budget is exhausted.
STEPS: list[tuple[str, Callable]] = [
    (probe.NAME, probe.run),
    (void.NAME, void.run),
    (shapes_found.NAME, shapes_found.run),
    (graphs.NAME, graphs.run),
    (classes.NAME, classes.run),
    (vocab.NAME, vocab.run),
    (profile.NAME, profile.run),
    (links.NAME, links.run),
    (namespaces.NAME, namespaces.run),
    (validate_step.NAME, validate_step.run),
]


# ---------------------------------------------------------------------------
# Arguments

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="baqueano", description="A pathfinder for unknown SPARQL endpoints.")
    parser.add_argument("--version", action="version", version=f"baqueano {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    explore = sub.add_parser("explore", help="discover what sits behind a SPARQL endpoint")
    explore.add_argument("endpoint", help="SPARQL endpoint URL")
    explore.add_argument("--out", default="./baqueano-out", metavar="DIR", help="output folder")
    explore.add_argument("--budget", type=float, default=300, metavar="SEC", help="maximum total discovery time")
    explore.add_argument("--timeout", type=float, default=30, metavar="SEC", help="per-query timeout")
    explore.add_argument("--sample", type=int, default=200, metavar="N", help="instances sampled per class")
    explore.add_argument("--max-classes", type=int, default=30, metavar="N", help="classes to profile")
    explore.add_argument("--graph", metavar="IRI", help="restrict discovery to one named graph")
    explore.add_argument("--class", dest="classes", action="append", default=[], metavar="IRI",
                         help="class to profile first, repeatable; full IRI or known prefix (e.g. wd:Q5)")
    explore.add_argument("--class-property", default="rdf:type", metavar="IRI",
                         help="property linking instances to classes (e.g. wdt:P31 for Wikidata)")
    explore.add_argument("--seed", type=int, default=1, metavar="N",
                         help="seed for random-offset sampling (same seed, same sample)")
    explore.add_argument("--delay", type=float, default=0.5, metavar="SEC", help="pause between queries")
    explore.add_argument("--header", action="append", default=[], metavar='"K: V"',
                         help="extra HTTP header, repeatable (prefer BAQUEANO_HEADER_* env vars for secrets)")
    explore.add_argument("--user-agent", default=DEFAULT_USER_AGENT, metavar="TEXT")
    explore.add_argument("--debug", action="store_true", help="detailed console logging")

    render_cmd = sub.add_parser("render", help="regenerate the outputs from a saved discovery.json (no queries)")
    render_cmd.add_argument("discovery_json", metavar="DISCOVERY_JSON", help="path to a discovery.json")
    render_cmd.add_argument("--out", metavar="DIR", help="output folder (default: the folder holding the JSON)")
    render_cmd.add_argument("--debug", action="store_true", help="detailed console logging")
    return parser


def validate(args: argparse.Namespace) -> str | None:
    """Return an error message for invalid arguments, or None."""
    if args.command != "explore":
        return None
    if not args.endpoint.startswith(("http://", "https://")):
        return f"endpoint must be an http(s) URL: {args.endpoint}"
    if args.budget <= 0 or args.timeout <= 0:
        return "--budget and --timeout must be positive"
    if args.delay < 0:
        return "--delay cannot be negative"
    if args.sample < 1 or args.max_classes < 1:
        return "--sample and --max-classes must be at least 1"
    if expand(args.class_property) is None:
        return f"--class-property: not an IRI or known prefix:name: {args.class_property}"
    for text in args.classes:
        if expand(text) is None:
            return f"--class: not an IRI or known prefix:name: {text}"
    return None


def parse_header(text: str) -> tuple[str, str]:
    """'Name: value' -> ('Name', 'value'). Raises ValueError if malformed."""
    name, sep, value = text.partition(":")
    if not sep or not name.strip():
        raise ValueError(f'header must look like "Name: value", got {text!r}')
    return name.strip(), value.strip()


def headers_from_env(environ: dict[str, str]) -> dict[str, str]:
    """BAQUEANO_HEADER_X_API_KEY=... -> {'X-Api-Key': ...}."""
    headers = {}
    for key, value in environ.items():
        if key.startswith(ENV_HEADER_PREFIX) and len(key) > len(ENV_HEADER_PREFIX):
            name = key[len(ENV_HEADER_PREFIX):].replace("_", "-").title()
            headers[name] = value
    return headers


# ---------------------------------------------------------------------------
# Orchestration

def run_steps(client, ctx: Context, steps=STEPS) -> list[StepResult]:
    """Run the pipeline in order. Stops early only when the probe fails."""
    for name, run in steps:
        try:
            result = run(client, ctx)
        except Exception as e:  # a bug in one step must not lose the whole run
            logger.exception("step %s crashed", name)
            result = StepResult(name, model.ERROR, f"internal error: {type(e).__name__}: {e}")
        ctx.discovery.steps.append(result)
        print(f"  {result.name:<28} {result.status:<11} {result.message or ''}", file=sys.stderr)
        if name == probe.NAME and result.status != model.OK:
            break
    return ctx.discovery.steps


def exit_code(steps: list[StepResult]) -> int:
    if not steps or steps[0].name != probe.NAME or steps[0].status != model.OK:
        return EXIT_ERROR
    if all(s.status in COMPLETE_STATUSES for s in steps):
        return EXIT_OK
    return EXIT_DEGRADED


def write_outputs(out: Path, discovery: Discovery) -> None:
    """Everything except queries.log (written as queries go).

    discovery.json goes first: it is the source of truth, and a bug in a
    generator must not lose it. Each generator then runs on its own.
    """
    path = out / "discovery.json"
    path.write_text(json.dumps(discovery_to_dict(discovery), indent=2, ensure_ascii=False) + "\n",
                    encoding="utf-8")
    write_generated(out, discovery)


def write_generated(out: Path, discovery: Discovery) -> None:
    """The files derived from the discovery: report, shapes, diagram, queries."""
    if discovery.found_shapes_ttl:
        (out / "found-shapes.ttl").write_text(discovery.found_shapes_ttl, encoding="utf-8")

    for file_name, generator in (("report.md", report.render), ("shapes.ttl", shapes_gen.render),
                                ("schema.mmd", diagram.render)):
        try:
            (out / file_name).write_text(generator(discovery), encoding="utf-8")
        except Exception:
            logger.exception("could not generate %s", file_name)

    try:
        files = queries_gen.render(discovery)
    except Exception:
        logger.exception("could not generate queries")
        return
    queries_dir = out / "queries"
    queries_dir.mkdir(exist_ok=True)
    for old in queries_dir.glob("[0-9][0-9]-*.rq"):   # stale files from a previous run
        old.unlink()
    for file_name, text in files.items():
        (queries_dir / file_name).write_text(text, encoding="utf-8")


def explore(args: argparse.Namespace) -> int:
    headers = headers_from_env(dict(os.environ))
    for text in args.header:
        name, value = parse_header(text)
        headers[name] = value
    if headers:
        logger.debug("sending %d extra header(s): %s", len(headers), ", ".join(sorted(headers)))

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    class_property = expand(args.class_property)
    requested = list(dict.fromkeys(expand(c) for c in args.classes))
    discovery = Discovery(
        endpoint=args.endpoint,
        started_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        graph_scope=args.graph,
        class_property=class_property,
        requested_classes=requested,
        sample_seed=args.seed,
    )
    ctx = Context(discovery, Settings(sample=args.sample, max_classes=args.max_classes, graph=args.graph,
                                      class_property=class_property, classes=requested, seed=args.seed))

    logger.debug("settings: budget=%ss timeout=%ss delay=%ss sample=%d max_classes=%d graph=%s "
                 "class_property=%s classes=%s seed=%d", args.budget, args.timeout, args.delay, args.sample,
                 args.max_classes, args.graph, class_property, requested, args.seed)
    print(f"baqueano: exploring {args.endpoint} (budget {args.budget:.0f}s) -> {out}", file=sys.stderr)
    with open(out / "queries.log", "w", encoding="utf-8") as log_file:
        def log(entry: dict) -> None:
            log_file.write(json.dumps(entry, ensure_ascii=False) + "\n")
            log_file.flush()

        client = SparqlClient(
            args.endpoint,
            budget=Budget(args.budget),
            timeout_s=args.timeout,
            delay_s=args.delay,
            headers=headers,
            user_agent=args.user_agent,
            log=log,
        )
        try:
            run_steps(client, ctx)
        except KeyboardInterrupt:
            print("baqueano: interrupted, writing what was discovered so far", file=sys.stderr)
            write_outputs(out, discovery)
            return EXIT_DEGRADED
        finally:
            client.close()

    write_outputs(out, discovery)
    code = exit_code(discovery.steps)
    if code == EXIT_ERROR:
        print(f"baqueano: the endpoint did not answer; details in {out / 'queries.log'}", file=sys.stderr)
    else:
        print(f"baqueano: {len(discovery.classes)} classes, {len(discovery.profiles)} profiled, "
              f"{len(discovery.links)} links, {len(discovery.graphs)} named graph(s)", file=sys.stderr)
        print(f"baqueano: start with {out / 'report.md'}", file=sys.stderr)
    return code


def load_discovery(path: Path) -> tuple[Discovery | None, str | None]:
    """Read a saved discovery.json. Returns (discovery, None) or (None, one-line error)."""
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as e:
        return None, f"cannot read {path}: {e}"
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        return None, f"{path} is not valid JSON: {e}"
    if not isinstance(data, dict):
        return None, f"{path} is not a discovery.json (expected a JSON object)"
    try:
        return model.discovery_from_dict(data), None
    except (TypeError, ValueError, AttributeError) as e:
        return None, f"{path} is not a discovery.json: {e}"


def render(args: argparse.Namespace) -> int:
    """Regenerate the outputs from a saved discovery.json, without any query.

    discovery.json itself is left untouched, and so is queries.log.
    """
    source = Path(args.discovery_json)
    discovery, error = load_discovery(source)
    if error:
        print(f"baqueano: {error}", file=sys.stderr)
        return EXIT_ERROR
    out = Path(args.out) if args.out else source.parent
    out.mkdir(parents=True, exist_ok=True)
    write_generated(out, discovery)
    print(f"baqueano: rendered {source} -> {out}", file=sys.stderr)
    return EXIT_OK


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.debug else logging.WARNING,
        format="%(levelname)s %(name)s: %(message)s",
    )
    if not args.debug:
        # httpx logs every request at INFO; keep it quiet unless debugging.
        logging.getLogger("httpx").setLevel(logging.WARNING)
    # httpcore's DEBUG output is wire-level; never show it (headers may hold secrets).
    logging.getLogger("httpcore").setLevel(logging.WARNING)

    error = validate(args)
    if error is None and args.command == "explore":
        try:
            for text in args.header:
                parse_header(text)
        except ValueError as e:
            error = str(e)
    if error:
        parser.error(error)  # exits with code 2

    if args.command == "explore":
        return explore(args)
    if args.command == "render":
        return render(args)
    return EXIT_ERROR

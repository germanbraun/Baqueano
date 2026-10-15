# Baqueano — conventions for Claude Code

Read SPEC.md before changing behaviour. It is the source of truth for scope,
pipeline steps, outputs and milestones.

## Working agreement

- Work milestone by milestone (SPEC.md, "Implementation plan"). Do not start
  the next milestone until the current one's tests pass and the user confirms.
- The user debugs by hand: prefer the clearest code over the cleverest.
  Small modules, pure functions, explicit `if` branches over abstractions.

## Architecture rules

- Only `baqueano/client.py` touches the network.
- Only `baqueano/cli.py` writes files. The client receives a log callback
  for `queries.log`; it never opens files itself.
- `baqueano/model.py` holds dataclasses only: no I/O, no network.
- Each step is `run(client, ctx) -> StepResult` in `baqueano/steps/`.
  Steps fill `ctx.discovery`; the CLI appends the returned StepResult.
- Each generator (milestone 4) is `render(discovery) -> str` and reads only
  the Discovery (i.e. what `discovery.json` holds).
- `--graph` scoping goes through `baqueano/scope.py`, never inline.

## Errors

- Expected failures (timeout, HTTP error, bad response, budget) are statuses,
  not exceptions. `SparqlClient` never raises on network or endpoint errors;
  it returns a `QueryOutcome` with a status.
- Step statuses: `ok | sampled | timeout | skipped | unsupported | error`.
  `error` is for HTTP/parse failures that are not a clear "unsupported".
- A failing step never stops the pipeline (except a failed probe, which
  means the endpoint is unreachable: exit code 2).

## Secrets

- Headers from `--header` or `BAQUEANO_HEADER_*` are never written to
  `queries.log`, `discovery.json` or debug output.

## Logging

- Use the `baqueano` logger (`logging.getLogger(__name__)`). `--debug` turns
  on DEBUG; log every fallback decision and every threshold applied.

## Tests

- `.venv/bin/pytest` must pass before handing work back.
- Unit tests never use the network: steps use `tests/fakes.FakeClient`,
  the client uses `httpx.MockTransport`.
- Python 3.10+: `X | None` syntax is fine, no `match` needed.

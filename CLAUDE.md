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
- Each generator in `baqueano/generate/` is `render(discovery) -> str`
  (`queries.render` returns `{file name: text}`) and reads only the Discovery,
  i.e. what `discovery.json` holds. Output must be deterministic: the same
  discovery renders byte-for-byte the same (diffable between runs).
- Shape and query thresholds live only in `generate/thresholds.py`.
- Raw samples (`ctx.samples`, `profiling.Sample`) live only in memory for the
  validate step; discovery.json keeps the validation results, not the sample.
  So `render` can redraw the data-quality section but cannot re-validate.
- `validation.py` checks a SHACL Core subset. An unsupported feature must be
  added to `validation_not_checked` with a reason, never silently skipped.
- `--graph` scoping goes through `baqueano/scope.py`, never inline.

## Errors

- Expected failures (timeout, HTTP error, bad response, budget) are statuses,
  not exceptions. `SparqlClient` never raises on network or endpoint errors;
  it returns a `QueryOutcome` with a status.
- Step statuses: `ok | sampled | timeout | skipped | unsupported | error`.
  `error` is for HTTP/parse failures that are not a clear "unsupported".
- A failing step never stops the pipeline (except a failed probe, which
  means the endpoint is unreachable: exit code 2).
- Exit code 1 means some step is `sampled`, `timeout`, `skipped` or `error`.
  `ok` and `unsupported` count as complete. Something simply not published
  (no VoID, no shapes) is `ok` with a message saying so.
- Fallback figures (VoID-declared counts, samples) are always marked as not
  exact in the model (`count_exact`, `triple_count_exact`) so the report can
  say so.
- Steps with several sub-queries combine statuses with `context.worst()`.
- Client step labels (`"classes:sample"`, `"void:partitions"`, ...) identify
  queries in queries.log and are the keys FakeClient answers by.

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

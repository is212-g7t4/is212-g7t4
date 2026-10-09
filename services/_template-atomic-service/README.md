# _template-atomic-service

Minimal, non-working skeleton demonstrating the file structure an **atomic**
service should follow (owns one entity + its own data store, never calls
another service). Copy this directory to start a real atomic service — see
[INDEX.md](../../INDEX.md) for the list of atomics still to be created, and
[AGENTS.md](../../AGENTS.md) for the conventions this follows.

For the composite-service pattern (a service that *is* allowed to call other
services), see [`../_template-composite-service/`](../_template-composite-service/).

## Structure

```
app/
├── __init__.py   # Flask app factory
├── routes.py     # blueprint(s) — currently just a /health stub
└── models.py     # placeholder for this service's data model(s)
tests/
├── __init__.py
└── unit/             # mocked tests; CI always runs these
    ├── __init__.py
    └── test_health.py
```

Add a `tests/integration/` package only if this service grows a test that needs
a real database or another running service. Mark those `integration` so they
stay out of CI — see [AGENTS.md](../../AGENTS.md#testing-expectations).

## Commands

```
uv sync
uv run flask --app app run --debug
uv run pytest
```

`uv run pytest` takes no flags: every pytest and coverage setting is in
`pyproject.toml`.

## After copying this template

`fail_under` in `[tool.coverage.report]` is `100`, which is true of the
`/health` stub alone. Once this becomes a real service with real code, set it
to the coverage you have actually reached, then raise it in each PR that adds
tests. CI fails any PR that drops a service below its floor.

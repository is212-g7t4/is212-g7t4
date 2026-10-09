# _template-composite-service

Minimal, non-working skeleton demonstrating the file structure a
**composite** service should follow (orchestrates atomics/Forum/the broker,
holds no data of its own). Copy this directory to start a real composite
service — see [INDEX.md](../../INDEX.md) for the list of composites still to
be created, and [AGENTS.md](../../AGENTS.md) for the conventions this
follows.

For the atomic-service pattern (a service that owns one entity + its own
data store and never calls out), see
[`../_template-atomic-service/`](../_template-atomic-service/).

## Structure

```
app/
├── __init__.py   # Flask app factory
├── routes.py     # blueprint(s) — currently just a /health stub
└── clients.py    # thin HTTP wrappers for calling downstream services
tests/
├── __init__.py
└── unit/             # mocked tests; CI always runs these
    ├── __init__.py
    └── test_health.py
```

Note there's no `models.py` — composites don't own a database.

Add a `tests/integration/` package only if this service grows a test that needs
another running service. Mark those `integration` so they stay out of CI — see
[AGENTS.md](../../AGENTS.md#testing-expectations).

## Commands

```
uv sync
uv run flask --app app run --debug
uv run pytest
```

`uv run pytest` takes no flags: every pytest and coverage setting is in
`pyproject.toml`. Unit tests run with sockets blocked, so a `clients.py` call
that isn't mocked fails loudly instead of reaching a real service.

## After copying this template

`fail_under` in `[tool.coverage.report]` is `61`, which is all the `/health`
stub reaches with `clients.py` untested. Once this becomes a real service, set
it to the coverage you have actually reached, then raise it in each PR that adds
tests. CI fails any PR that drops a service below its floor.

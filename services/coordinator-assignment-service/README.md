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
└── test_health.py
```

Note there's no `models.py` — composites don't own a database.

## Commands

```
uv sync
uv run flask --app app run --debug
uv run pytest
```

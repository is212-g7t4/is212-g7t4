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
└── test_health.py
```

## Commands

```
uv sync
uv run flask --app app run --debug
uv run pytest
```

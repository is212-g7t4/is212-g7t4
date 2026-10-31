# Equipment Service (atomic)

The equipment catalogue: list and add records in `public."Equipment"`. No
reservation data: Equipment Request owns the request rows and final approval
transaction; Equipment Reservation supplies catalogue/event inputs and read-time
availability. Called directly by the frontend, and being an atomic it calls no
other service.

## OO model

`app/equipment.py` implements the Equipment class diagram: an `Equipment`
base class plus `Microphone`, `LightingKit`, `Projector`, `Laptop`,
`Furniture` (with `Table` and `Chair`) and `Speaker`. Each overrides
`get_setup_requirements()`, and `from_row()` picks the subclass from
`equipment_type`, so every API item carries the setup text for its own type.

## Run

```
cd services/equipment-service  # from the repo root
# Configure .env from this service's .env.example first; keep existing settings.
uv sync --locked --python 3.12
uv run --env-file .env flask --app app run --port 5002
```

Or, from the repository root, `docker compose up --build equipment-service`
(port 5002); choose host or Docker execution, not both on the same port.

## Endpoints

- `GET /equipment[?status=Available|Unavailable]` — catalogue
  ordered by type, then description. `400` for an unknown status.
- `POST /equipment` — add a record. Body:
  `{"equipmentType", "description", "totalQuantity", "location", "status"?}`
  (`status` defaults to `Available`). Returns `201` with the record. `equipmentType` can be any text up to 100
  characters: the 8 known types map to their subclass (any casing is
  canonicalised), anything else is stored as given and uses the base
  `Equipment` class.
  `400` on validation errors (empty `equipmentType` or text, quantity
  not a whole number ≥ 0), `401` without a valid sign-in token, `403` unless
  the token's role is Technical Support.

Every endpoint needs a Supabase access token (`Authorization: Bearer
<token>`, SCRUM-8); the caller's role comes from the token.

Item shape: `{id, type, description, totalQuantity, location, status,
setupRequirements}`. `503` if the database is unreachable or `DATABASE_URL`
is unset.

## Tests and seeding

```
uv run pytest                             # unit tests; coverage settings live in pyproject.toml
uv run python scripts/seed_equipment.py   # idempotent mock catalogue
```

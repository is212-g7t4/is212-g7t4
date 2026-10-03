# Equipment Service (atomic)

The equipment catalogue: list and add records in `public."Equipment"`. No
reservation data (that belongs to the equipment availability and reservation
services). Called directly by the frontend, and being an atomic it calls no
other service.

## OO model

`app/equipment.py` implements the Equipment class diagram: an `Equipment`
base class plus `Microphone`, `LightingKit`, `Projector`, `Laptop`,
`Furniture` (with `Table` and `Chair`) and `Speaker`. Each overrides
`get_setup_requirements()`, and `from_row()` picks the subclass from
`equipment_type`, so every API item carries the setup text for its own type.

## Run

```
cp .env services/equipment-service/.env   # from the repo root
cd services/equipment-service
uv sync
uv run --env-file .env flask --app app run --port 5002
```

Or `docker compose up --build equipment-service` (port 5002).

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
  not a whole number ≥ 0), `401` without the DEV headers, `403` unless the
  role is Technical Support.

DEV auth: `X-Dev-User-Id` (UUID) and `X-Dev-Role` headers, as in Venue
Availability Service. These can be spoofed; replace with Supabase JWT
verification when real auth lands.

Item shape: `{id, type, description, totalQuantity, location, status,
setupRequirements}`. `503` if the database is unreachable or `DATABASE_URL`
is unset.

## Tests and seeding

```
uv run pytest --cov=app --cov-report=term-missing
uv run python scripts/seed_equipment.py   # idempotent mock catalogue
```

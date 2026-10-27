# E2E journeys: traceability

Real-stack Playwright journeys. Manual and opt-in (never in CI): start the stack, then `npm run test:journeys` from the repo root.

| Journey | Spec | Jira task | User stories exercised | Fixture-only dependencies | Status |
|---|---|---|---|---|---|
| J5a Prevent conflicting venue reservations | `J5/J5a-venue-conflict/` | SCRUM-259 | SCRUM-28, 29, 30, 154 | SCRUM-11, 159, 19 | Implemented (buffer conflict, resubmit, approval); SCRUM-155, 145, 146, 147, 156 left to integration tests |
| J5b Prevent equipment over-allocation | `J5/J5b-equipment-over-allocation/` | SCRUM-259 | SCRUM-32, 33, 34, 35 | SCRUM-31, 11, 159, 19 | Implemented |

Other journeys (J1 to J4, J6 to J8; SCRUM-255 to 258, 260 to 262) get a row here when their spec is added.

## Adding a journey

1. Create one `J<n>/` folder for the Jira journey. Keep its main spec and alternate paths in that folder; put distinct paths in child folders or files, such as `J5/J5a-venue-conflict/` and `J5/J5b-equipment-over-allocation/`.
2. Put reusable helpers for all E2E suites in `e2e/helpers/`. Put helpers and fixture scripts used only by one journey/path alongside it under `J<n>/`; never add journey-specific setup to the global helper folder.
3. Set up data through service APIs (not UI clicks) and make fixture event names follow `J<n>[a|b] Event ...` (the pattern in `e2e/helpers/cleanup.ts`) so they are removed after the run.
4. Use `test.step` for each stage of the journey.
5. Add the row above.

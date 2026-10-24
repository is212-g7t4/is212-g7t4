# E2E journeys: traceability

Real-stack Playwright journeys. Manual and opt-in (never in CI): start the stack, then `npm run test:journeys` from the repo root.

| Journey | Spec | Jira task | User stories exercised | Fixture-only dependencies | Status |
|---|---|---|---|---|---|
| J5a Prevent conflicting venue reservations | `J5a-venue-conflict/` | SCRUM-259 | SCRUM-28, 29, 30, 154, 155, 156, 145, 146, 147 | | Placeholder (`test.fixme`); blocked on SCRUM-28 and SCRUM-29 |
| J5b Prevent equipment over-allocation | `J5b-equipment-over-allocation/` | SCRUM-259 | SCRUM-32, 33, 34, 35 | SCRUM-31, 11, 159, 19 | Implemented |

Other journeys (J1 to J4, J6 to J8; SCRUM-255 to 258, 260 to 262) get a row here when their spec is added.

## Adding a journey

1. Create `J<n>-<name>/J<n>-<name>.spec.ts`, with the story keys in the header comment.
2. Put setup in `helpers/` (API calls, not UI clicks) and make fixture event names match the pattern in `helpers/cleanup.ts` (`J5% Event %` today; extend it for new journeys) so they are removed after the run.
3. Use `test.step` for each stage of the journey.
4. Add the row above.

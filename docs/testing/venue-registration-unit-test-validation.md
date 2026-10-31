# Venue and registration unit-test validation

Validated on 1 November 2026 for:

- `venue-availability-service`
- `venue-service`
- `venue-booking-service`
- `attendee-registration-service`
- `registration-service`

## Result

All five unit suites pass in their locked environments on Windows after
disabling `.env` loading during test collection and adding the Windows-only
`tzdata` dependency required by `ZoneInfo("Asia/Singapore")`.

| Service | Result | Line and branch coverage |
|---|---:|---:|
| Venue Availability | 548 passed | 100% |
| Venue | 182 passed | 100% |
| Venue Booking | 531 passed | 100% |
| Attendee Registration | 116 passed | 100% |
| Registration | 131 passed | 100% |

The runs used the repository configuration rather than hand-written pytest
flags, except that `tests/unit` was selected explicitly because this review is
of the unit tier. Integration and live tests were not used as evidence here.

## Acceptance-criteria validation

The test modules reproduce the applicable Jira user story and acceptance
criteria, then state what runs for real, what is doubled and what the module
does not prove. Every one of the 741 test functions has a docstring describing
its asserted behaviour, traceability or supporting-design purpose, and test
double boundary.

The detailed naming/docstring pass classifies **669 tests as AC evidence** and
**72 as supporting design, boundary or regression checks**:

- AC evidence uses `test_ac<n>_...`; a test covering several criteria lists
  each one in the prefix.
- When a shared module proves an AC for a ticket other than the filename's
  primary ticket, its name uses `test_scrum<key>_ac<n>_...` so the attribution
  is not ambiguous.
- Checks with no direct AC claim use `test_support_...`; they are not presented
  as acceptance evidence merely because they improve code coverage.

All 741 names agree with the AC references in their function docstrings. Every
function docstring has a `Summary` and `Double` line. Environment, clock, HTTP,
database and downstream-service doubles are identified explicitly; one unused
`monkeypatch` fixture was removed. Module-level `Not proven` sections now name
the omitted ACs and point to the sibling module, owning service, frontend,
integration tier or E2E journey where that evidence belongs.

Coverage is intentionally distributed across service boundaries. An AC is not
considered missing merely because one atomic or composite covers only its part
of the workflow. In particular:

- SCRUM-9 is covered across Registration, Attendee Registration and Venue
  Availability for both allowed and refused reads.
- SCRUM-10 route-level role and relationship enforcement is covered across all
  five services. The remaining persistence proof is recorded under gaps below.
- SCRUM-24, 25, 30, 37, 38, 47, 145, 148, 154, 155, 157, 167, 170, 171, 173
  and 174 have their service-owned AC behaviour represented in these unit
  suites.
- SCRUM-26 is split between Venue's catalogue filters and Venue Availability's
  booking/closure window. Form reset, messages and elapsed-time presentation
  remain frontend/E2E responsibilities.
- SCRUM-28 and 29 are split between focused submission/review modules and
  lower-level booking regression tests. Inputs, stored SQL parameters, returned
  status/error payloads and immutable-state behaviour are asserted.
- SCRUM-37 to 41 are split between Registration's record/count ownership and
  Attendee Registration's event/user orchestration. Tests assert caller identity
  from the token, exact downstream inputs and the composite response shape.
- SCRUM-46 AC1 and AC2 are covered by both the composite detail capture and the
  atomic outbox boundary. AC3 belongs to Event Service and is not falsely
  simulated in these services.
- SCRUM-150 and 153 tests cover only the attendee-visible-details part of those
  stories. Safety decisions, event state changes and history belong to Safety
  Check/Event Service.
- SCRUM-156, 157 and 164 share booking primitives. The booking tests preserve
  the workflow rule that one venue arrangement can be changed, cancelled or
  reset without mutating unrelated bookings.

## Input and output checks

The reviewed tests cover normal, boundary, conflict and failure inputs rather
than only happy paths. Representative checks include malformed UUIDs and JSON,
missing mandatory fields, invalid enums and timestamps, overlap boundaries,
capacity/full-event conflicts, duplicate registration, late withdrawal,
wrong-role and wrong-owner access, absent internal credentials, database and
downstream failures, and idempotent cancellation/withdrawal paths.

Outputs are checked at the observable service boundary: HTTP status, stable
error code/message, complete response shape, SQL parameters or downstream
request arguments, transaction commit/rollback, and proof that forbidden or
invalid requests do not perform the write or downstream call. This preserves
the user-story workflow instead of bypassing upstream ownership rules.

## Redundancy review

No exact duplicate test bodies exist within any of the five unit suites.
Similar authentication, CORS and access-control cases across services are not
redundant: each independently deployable service owns and must enforce the same
boundary. Focused modules that share a Jira story also test different layers
(for example route contract versus SQL/transaction regression) and should not
be collapsed.

Support-only health, CORS, seed and infrastructure modules retain neutral
filenames because they are not acceptance tests for a Jira story. Story-owned
modules use `test_scrum<key>_<description>.py`; where one ticket needs multiple
focused modules, the suffix identifies the distinct responsibility.

## Gaps and follow-up evidence

These are genuine evidence gaps, not reasons to weaken a unit assertion:

1. **SCRUM-10 rejected-registration persistence:** Registration unit tests prove
   that refused route paths do not invoke a write, but no real-PostgreSQL
   integration test proves the existing row remains unchanged. Add an
   integration case for wrong owner/wrong role and compare the row before and
   after.
2. **SCRUM-114 AC2 refresh timing:** Venue tests prove the updated status is
   serialized, but no maintained browser test proves it becomes visible within
   30 seconds. This needs a frontend timer/refetch test or a real-stack journey,
   not another atomic unit test.
3. **SCRUM-23 AC4 end-to-end exclusion:** Venue validates the `Booked` and
   `Under Maintenance` statuses, but these five suites do not alone prove that
   both search and calendar hide such venues. The owning search composite and
   calendar integration/E2E evidence must remain traceable to this AC.
4. **UI-only AC halves:** Add/edit forms, empty-state and success messages,
   clear-filter behaviour, buttons, and visual calendar blocking are outside
   Flask unit-test observability. Their module docstrings point to frontend or
   E2E coverage; those references should be revalidated whenever the relevant
   frontend tests are renamed or retired.
5. **Windows collection was previously non-reproducible:** the lockfiles now
   include `tzdata` on Windows. Keep that marker in every service that imports
   `ZoneInfo` in application or test collection code.
6. **SCRUM-46 venue-context edge cases:** Attendee Registration does not yet
   test selection from several approved bookings (earliest start, then lowest
   id), ignoring non-approved bookings, or Venue Service lookup failures. The
   implementation contains these rules, but unit evidence is still needed.
7. **Mixed-outcome AC scenarios:** SCRUM-10 AC5 is represented by separate
   allowed and refused paths, but not one test applying both outcomes across
   two events. SCRUM-156 AC5 likewise has separate booking success/conflict
   tests but no single event scenario proving one failed booking does not block
   another valid booking.

No unit test was found that reverses the intended user-story sequence, derives
caller identity from request data, lets an atomic call another service, or
turns notification delivery into a synchronous success dependency.

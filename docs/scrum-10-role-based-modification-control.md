# SCRUM-10 — Role-Based Modification Control for Events

The write-side counterpart of SCRUM-9 (role-based viewing). Every user-facing write route now decides
who may change something from the **role in the caller's token**, and only then looks at the caller's
relationship to the record.

## Story and acceptance criteria

**Story:** As a registered user, I want to modify only information appropriate to my role and relationship to an event, so that I can perform my responsibilities without changing information outside my permissions.

- **AC1:** Given an authenticated user is permitted to modify information based on their role and relationship to the event, when they make a valid change to that information, then the change is allowed.
- **AC2:** Given an authenticated user's role does not permit them to modify particular information, when they attempt to change that information, then the modification is prevented and the existing information remains unchanged.
- **AC3:** Given an authenticated user's relationship to an event does not permit them to modify that event's information, when they attempt to make a change, then the modification is prevented and the existing information remains unchanged.
- **AC4:** Given a user is permitted to view particular information but is not permitted to modify it, when they attempt to change that information, then the modification is prevented while their permitted viewing access remains unaffected.
- **AC5:** Given a user is permitted to modify information for one event but does not have the required access to another event, when they attempt to modify information for both events, then only modifications to information for which they have the required access are allowed.

## The rule

For every write route, in this order:

1. **Role** (`g.role`, from the `user_role` claim of the verified Supabase token). A role that may not make this change gets `403` and nothing is read or written. The check runs first in the handler, before the body is parsed or the database is touched.
2. **Relationship** (owner of the draft, coordinator assigned to the event, owner of the registration). A wrong relationship is also `403`.
3. **State** (for example "only drafts can be edited"). Wrong state is `409`.

The refusal for a wrong role is `403 {"message": "Your role cannot change this information."}`. Venue Service uses `{"code": "VENUE_STAFF_ONLY", ...}` and Event Workflow keeps `code: NOT_ASSIGNED_COORDINATOR`, because their clients already read those codes.

Each service keeps its own small helper (`_cannot_modify`, or the service's existing `authorise` / `_venue_staff`); there is no shared library (see AGENTS.md).

## Who may change what

"Coordinators" means `Event Coordinator` and `Event Coordinator Lead`.

| Service | Route | Allowed roles | Also required |
|---|---|---|---|
| event | `POST /events`, `POST /events/drafts`, `PATCH`/`DELETE /events/drafts/<id>`, `POST /events/drafts/<id>/submit` | Event Organiser | owns the draft |
| event | `POST /events/<id>/change-requests`, `PATCH .../clarification-response`, `PATCH .../amendment-response` | Event Organiser | owns the event |
| event | `PATCH /events/<id>` (assign coordinator) | Event Coordinator Lead | |
| event | `PATCH .../progress`, `/approve`, `/reject`, `/clarification-request`, `/amendment-request`, `/details` | Coordinators | assigned to the event (the Lead may also edit an unassigned event through `/details`) |
| event | `PATCH /change-requests/<id>/decision` | Coordinators | assigned to the event; internal token |
| event | `PATCH /events/<id>/safety-status` | submit, withdraw, restore: Coordinators. Confirm, request changes, cancel: Safety Officer | internal token |
| venue | `POST /venues`, `PUT /venues/<id>`, `PUT /venues/<id>/safety-info` | Venue Staff | |
| venue-availability | `POST /venue-bookings`, `PATCH /venue-bookings/<id>`, `PATCH .../cancel` | Coordinators | |
| venue-availability | `PATCH .../approve`, `PATCH .../reject`, `POST /venue-holds` | Venue Staff | |
| venue-availability | `POST /venues/<id>/legacy-conflicts/reconcile` | Coordinators, Venue Staff, Technical Support | follows the booking-view roles because the read view triggers it |
| venue-availability | `POST /events/<id>/venue-bookings/safety-reset` | Safety Officer | internal token |
| venue-booking | `POST /booking-requests`, `PATCH /booking-requests/<id>`, `PATCH .../cancel` | Coordinators | |
| venue-booking | `PATCH .../review`, `/approve`, `/reject`; `PUT /venues/<id>` | Venue Staff | |
| safety-check | `POST /safety-checks`, `/resubmit`, `/recheck`, `/withdraw-for-venue-change`, `/restore-after-venue-change` | Coordinators | assigned to the event |
| safety-check | `POST /safety-checks/approve`, `/request-changes`, `/reject` | Safety Officer (looked up in User Service) | |
| safety-check-record | `POST /safety-check-records`, `DELETE .../<id>`, `POST .../withdraw`, `POST .../restore` | Coordinators | |
| safety-check-record | `PATCH .../decision`, `POST .../reopen` | Safety Officer | |
| registration, attendee-registration | `POST /registrations`, `PATCH /registrations/<id>/withdraw` | Attendee | owns the registration |
| event-workflow | `PATCH /events/<id>/details` | Coordinators | Event Service checks the assignment |
| event-workflow | `PATCH /change-requests/<id>` | Coordinators (looked up in User Service) | |
| equipment | `POST /equipment` | Technical Support | |
| equipment-request, equipment-reservation | create request | Coordinators | |
| equipment-request, equipment-reservation | review (approve or reject) | Technical Support | |
| equipment-request | `POST /events/<id>/equipment-requests/safety-reset` | Safety Officer | internal token |
| coordinator-assignment | `POST /events/<id>/assign-coordinator/<id>` | Event Coordinator Lead | |
| notification | `PATCH /notifications/<id>` | the inbox owner | identity-scoped, no role gate by design |

These were already role-gated before this story and were not changed: `PUT /venues/<id>/safety-info`, `POST /venue-holds`, venue-booking review/approve/reject, the safety-check decisions, `PATCH /change-requests/<id>` in event-workflow, equipment, equipment-request and equipment-reservation create and review, and coordinator-assignment. Everything else in the table was added or tightened for this story.

## Internal tokens and RBAC

One shared secret (`INTERNAL_SERVICE_TOKEN`) is sent as the `X-Internal-Token` header. It does not identify a person, so it cannot be replaced by a role check. It is used in two ways:

- **Notification dispatchers**, which have no signed-in user, present it with no `Authorization` header. The six services they call (User, Venue, Venue Availability, Registration, Event, Equipment Request) accept a request with no `Authorization` header and a valid token. The other services do not; they refuse any request without a user token.
- **Service-only routes** also require it, alongside the caller's forwarded `Authorization`. It is sent by Safety Check Service and Event Workflow Service and checked on Event Service (`/safety-status`, the `/details` re-check and Lead path, `/change-requests*`) and on both `safety-reset` routes. These routes used to take a second header, `X-Internal-Service-Token`, but it held the same secret, so the two were merged. Because one secret is shared, holding it does not prove a call came through the workflow; separating those would need a second secret.

The token locks are **added to** the role checks, not in place of them: a locked route needs the right role and the token. When `INTERNAL_SERVICE_TOKEN` is not configured on Event Service, the locked routes answer `503 INTERNAL_AUTH_NOT_CONFIGURED` instead of skipping the check. A plain coordinator edit through `/details` needs no token.

`authenticate()` also rejects a token whose `sub` is empty, so a handler can rely on `g.user_id` being set for any request that reaches it in the services that no longer accept the worker bypass.

## Tests that prove each AC

Each file's header copies the story and lists every AC, including those it does not cover and why.

| Service | Unit | Integration |
|---|---|---|
| event | `tests/unit/test_scrum10_event_modification_access.py` | `tests/integration/test_event_modification_access.py` |
| venue | `tests/unit/test_scrum10_venue_modification_access.py` | `tests/integration/test_venue_modification_access.py` |
| venue-availability | `tests/unit/test_scrum10_booking_modification_access.py` | `tests/integration/test_booking_modification_access.py` |
| venue-booking | `tests/unit/test_scrum10_booking_request_modification_access.py` | |
| safety-check | `tests/unit/test_safety_modification_access.py` | |
| safety-check-record | `tests/unit/test_safety_record_modification_access.py` | |
| registration | `tests/unit/test_scrum10_registration_modification_access.py` | |
| attendee-registration | `tests/unit/test_scrum10_registration_modification_access.py` | |
| event-workflow | `tests/unit/test_event_details_modification_access.py` | |
| equipment-request | `tests/unit/test_scrum10_equipment_safety_reset_access.py` | `tests/integration/test_scrum48_equipment_notification_transactions.py` (`safety-reset` called as a Safety Officer) |

The lock changes are covered in Event Service by `test_infra_safety_status_internal_lock.py`, `test_scrum153_recheck_safety_after_high_impact_changes.py` and `test_scrum10_event_modification_access.py`. Nine services (attendee-registration, coordinator-assignment, equipment, notification, safety-check-record, safety-check, venue-booking, equipment-reservation, event-workflow) carry two tests in their SCRUM-8 authentication modules: an internal token alone is refused, and a token without a subject is refused.

Where it matters, the integration tests give the refused user the relationship (for example the named coordinator) so that only the role can stop them, and assert the stored row is unchanged afterwards.

Run, from a service directory: `uv run pytest` for the unit tier, and `PYTHON_DOTENV_DISABLED=1 uv run pytest -m integration --no-cov` for the integration tier with Docker running. See [testing/integration-testing.md](testing/integration-testing.md).

## Known gaps

1. **Equipment Request trusts a caller-supplied `notificationContext`.** Create and review take the event name, equipment names and recipient IDs from the request body and only check their shape. Nothing checks an internal token or the caller's origin, so a coordinator who calls Equipment Request directly (not through Equipment Reservation) can choose the recipients. An earlier version of the Equipment Request README said an internal token closed this; the code does not enforce that, and the README has been corrected. Fixing it needs a decision: require the internal token on those routes, or resolve the context inside the service.
2. **Frontend not audited** for the newly gated routes, apart from registration, which is already shown only to Attendees. A UI path may now receive a `403`.
3. **Integration coverage is partial.** The new gates in venue-booking, safety-check, attendee-registration and event-workflow are covered by unit tests only, and safety-check-record has no integration tier. Equipment Request's integration suite pins the image `postgres@sha256:2d2b8998d31037bf721cfdf764d76ba74171b4fab3431b7f72c27c56ddbdf9e3` and asserts it is already present locally; it never pulls it, so every test errors on a machine without it. CI pulls it; locally run `docker pull` on that digest first. With the image present all 66 tests pass.
4. **`/internal/*` paths** skip authentication in every service, including the ones with no such route. Harmless today, but a route added there would be unauthenticated.
5. **The service templates** (`_template-atomic-service`, `_template-composite-service`) still contain the internal-token bypass, so a service copied from them gets it back.
6. **Not run against a live stack.** The tests use tokens signed with a test key, so they do not prove that Supabase issues the `user_role` claim, and no end-to-end run with the dispatchers was done. Coverage floors (`fail_under`) were not raised.

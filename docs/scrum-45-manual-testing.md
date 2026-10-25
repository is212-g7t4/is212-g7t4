# SCRUM-45 manual testing — shared Supabase DEVELOPMENT

## 1. Portable startup and ownership

Run commands from the repository root. Existing private service configuration is
owner-managed: do not copy credentials between checkouts or print resolved config.
This source is an uncommitted review candidate, not a completed latest-main merge.

```sh
git branch --show-current
docker compose -p is212-g7t4 ps
# Frontend only; first check that port 5174 is free or owned by this checkout:
npm --prefix frontend/event-management-ui run dev -- --host localhost
```

Open **http://localhost:5174/**. Vite uses strict port 5174; do not start a second
listener or use broad port-kill commands. The long-running server must be owned by
the user's main session. A verification subprocess is not a persistent handover.

No assistant launcher or external Compose override is needed:

- Compose sets Coordinator Assignment's `EVENT_SERVICE_URL=http://event-service:5000`
  and `USER_SERVICE_URL=http://user-service:5000`, overriding stale service env-file
  localhost values without changing its DB/token settings.
- `frontend/event-management-ui/.env.development` contains only the public localhost
  service URLs (5001–5015). Vite precedence, highest first: explicit process env,
  `.env.development.local`, `.env.development`, `.env.local`, `.env`. For another
  deployment, use explicit process or local-mode overrides. No credentials belong
  in `VITE_*`. Production mode does not load development defaults.
- API/consumer DB and internal-token/broker configuration are unchanged. Keep
  existing owner-managed settings; do not run a schema migration just to restart.

For an **authorised targeted restart only**, using already verified/built images:

```sh
docker compose -p is212-g7t4 config --quiet
docker compose -p is212-g7t4 up -d --no-deps --no-build \
  event-service event-workflow-service event-notification-dispatcher \
  coordinator-assignment-service notification-service notification-consumer
```

Never replace this with an unscoped `up --build`, `down`, queue purge or volume
removal. Preserve RabbitMQ and all unrelated containers. A build alone does not
update the running code; read back image IDs and code hashes after a handover.

## 2. Readiness is not new delivery

The previous authorised rollout recorded Event outbox/type/lease/index/RLS checks,
change-request migration checks, existing-row preservation and read-only API/UI
smoke. Its historical evidence is summarized in
[verification summary](scrum-45-verification-summary.md); it is not a fresh shared
schema or delivery claim for later source changes. The new upstream withdrawal
migration is included in disposable tests, **not applied to shared development**.

Before acceptance, verify the deployed Event API, dispatcher and consumer match
the reviewed source, required forward migrations are present, and the intended
recipient can access the inbox. Health 200, an empty queue or a connected consumer
does not prove a new decision/assignment notification was delivered.

`NOTIFICATION_DEV_MODE` and **Viewing as → Select active user** are demo identity,
not production authentication. Use actual agreed team accounts, not only role
labels. Read-only smoke must not open a notification or mark it read/unread.
Manual A–E below persist changes and require an agreed test event and owner.

## 3. Persistent manual acceptance — actions for the tester

Use uniquely named team-approved events, and record their IDs, organiser,
assigned coordinator and expected action. Prefer separate events for approval,
rejection and reassignment. Delivery applies to **new supported transitions**;
there is no automatic historical backfill. The bell polls about every 25 seconds;
**Refresh notifications** is the explicit refresh control. Delivery is
asynchronous: refresh rather than repeating the business action.

### A. Initial assignment

1. Select an **Event Organiser** using **Viewing as / Select active user**.
2. Choose **Submit event**, complete required fields, click **Submit Request**
   (not **Save as Draft**). Record the resulting event ID.
3. Select the **Event Coordinator Lead**. Choose **Events → Unassigned requests**,
   click **Refresh queue**, find only your event, choose **Coordinator**, click
   **Assign**. For the Lead-decision scenario, choose the Lead as coordinator.
4. Switch back to the **original organiser account**. Open the bell
   (**Notifications, N unread**) → **View all notifications** →
   **Refresh notifications**. Expect
   `<username> has been assigned to coordinate <event name>.`
5. Its link has accessible name **Open notification** and visible
   **View details →**. Open it and verify the matching event and assignment.
   This marks the message read; a reload should preserve the read state.

### B. Approval

On another submitted event, assign the acting user first. Select that **actual
assigned Event Coordinator or Event Coordinator Lead**, then
**Events → Request review** (`/requests/review`) → **Refresh requests** →
**Approve Request**. Expect **Event Request Approved**.

As the original organiser, bell → **View all notifications** →
**Refresh notifications**; expect `<event name> was approved`. Open it and verify
Approved on the matching event. Initial assignment and approval are distinct
notifications. The Lead can see more requests, but decision buttons apply only
to events assigned to the selected user; Lead visibility is not blanket authority.

### C. Rejection

On a separate submitted/assigned event, select its actual assigned coordinator.
**Events → Request review → Refresh requests → Reject Request** opens
**Reject event request?**. Fill **Reason for rejection** (nonblank, at most 500
characters) → **Confirm rejection**. Expect **Event Request Rejected**.

As original organiser, refresh the inbox; expect the event name and submitted
reason. **Open notification / View details →** must open that event with Rejected
and exact **Rejection reason**. Verify read state survives reload. Do not reject
another person's existing request merely to exercise the button.

### D. Reassignment

As **Event Coordinator Lead**, on an eligible active assigned event choose
**Reassign Coordinator** (event details or its Request review card), select
**New coordinator**, then **Confirm Reassignment**. The organiser should receive
a separate named message linking to that event. Repeat with another coordinator
only if agreed: the older notification must keep its earlier coordinator name.
Selecting the current coordinator is a no-op/error and must not create a new
notification. Terminal/ineligible events may not expose this action.

### E. Isolation and existing notifications

Select the other **Event Organiser account**: it must not see your new messages.
Check **Unread only**, **Mark read**, **Mark unread**, **Load more** when present,
and reload persistence using **your test messages only**. Opening a notification
and Mark read/unread persist changes. Existing venue entries should still render;
old seed entries without a validated destination legitimately remain content-only.
Do not purge/replay the shared queue, inject failures, stop the broker or change
shared schema for manual testing. Leave agreed records for team cleanup; no
truncate/reset/bulk repair.

### F. Adjacent merged functionality: change requests (not a SCRUM-45 delivery claim)

The consolidated checkout also contains the merged change-request workflow.
For your own eligible Submitted/Under Review/Approved event, organiser details
expose **Request changes**. Change at least one field and provide **Reason or
justification**, then **Submit change request**. The original event stays unchanged
while Pending Review; only one pending request is permitted per event.
The assigned coordinator uses **Events → Change requests → Refresh requests**,
then **Approve changes** or **Reject changes**. Rejection opens
**Reject change request?**, with **Reason for rejection → Confirm rejection**.
These controls are distinct from initial **Approve Request / Reject Request**.
Do **not** assume every merged change-request or clarification action produces a
SCRUM-45 notification: the deployed event outbox accepts only the three types
listed above. No shared mutation path in this section was exercised in rollout.

## 4. If a new message does not arrive

Do not create repeated assignments/decisions blindly. Confirm original organiser,
event ID, selected actual coordinator, successful decision result and inbox
refresh. Ask the authorised operator to inspect local redacted worker diagnostics
and read-only outbox/NotificationFailure counts. Queue emptiness alone is not
proof of successful delivery.

A missing/blank coordinator `username` deliberately **holds** assignment delivery,
not fabricates a name. An authorised operator can inspect
`GET /internal/notification-outbox/held` using the internal token; after correcting
that exact user, release only that source using the documented internal release
endpoint. Do not paste tokens into chat or perform bulk repair.

## 5. Isolated automated checks remain a separate environment

The former branch-owned SCRUM-45 E2E suite used disposable Docker PostgreSQL/RabbitMQ,
synthetic identities, separate owner DBs and disabled dotenv. It was **not** shared
Supabase acceptance. Earlier consolidated-suite evidence includes 26 delivery
acceptance cases and five migration cases, alongside broader unit/build checks;
this rollout did not rerun or reinterpret those as shared delivery.

The SCRUM-45 E2E suite above is historical evidence, not a current command:
its branch-owned tests have been handed off. Use the service-local commands in
`services/event-workflow-service/README.md`: each owning service now has
`tests/unit/test_scrum45_notifications.py` and
`tests/integration/test_scrum45_notifications.py`; Event also owns
`tests/integration/test_infra_migrations.py`. These are single-service checks,
not shared acceptance. Do not use `-m live`, shared credentials, or rerun baseline
migrations on the populated development DB. Kept `scripts/` tooling retains its
functionality; the manual launcher's ordinary resource/database helpers now live
in `scripts/scrum45_support/`, separate from service integration fixtures.
**Remaining acceptance:** a tester completes and records A–E on agreed new events
through this deployed stack. Until then, report **deployed/readiness verified**,
not “shared end-to-end notification delivery passed.”

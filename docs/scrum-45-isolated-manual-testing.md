# SCRUM-45: optional isolated manual notification sandbox

## Checkout and scope

Run from the repository root of the reviewed checkout. This is an optional,
disposable **manual environment**, not a second required shared-development test
pass or a pytest fixture held open. It runs until Ctrl-C and does not validate
production authentication. The current candidate is uncommitted; no commit or PR
is implied. Follow the [team integration standard](testing/integration-testing.md)
and [verification summary](scrum-45-verification-summary.md) for automated scopes.

## Prerequisites

- Docker running; `docker info` must succeed. Images: `postgres:17.6` and
  `rabbitmq:4-management` (Docker may download missing images).
- `uv`, Node/npm, and Python 3.12 compatible with the service environments.
- These six service environments must already exist:
  `event-service`, `notification-service`, `user-service`,
  `coordinator-assignment-service`, `venue-availability-service`, and
  `event-workflow-service`. If missing, run `uv sync --locked` from each
  respective `services/<name>` directory. This installs dependencies, not a
  service or migration. Do **not** create/copy `.env` files.
- Frontend dependencies: if missing, `npm ci` in
  `frontend/event-management-ui`.
- A normal browser is sufficient for manual use. Reproducing the recorded
  automated browser evidence additionally requires the frontend's Playwright
  Chromium installation (`npx playwright install chromium`).

The validation machine already had the required service and frontend
installations. Fresh-machine package/image downloads are prerequisites, not
claimed offline-tested behavior.

## Start: copy these commands exactly

```bash
# From the repository root; use a new state directory for every launch.
uv run --no-project --with pytest --with httpx --with psycopg2-binary python scripts/scrum45_manual_sandbox.py --state-dir "${TMPDIR:-/tmp}/scrum45-manual-$(date +%Y%m%d-%H%M%S)"
```

Keep the terminal open. Wait for **`READY http://127.0.0.1:<generated-port>`**;
open that exact address, not an existing browser tab on port 5174. Startup also
prints an absolute **`START COMMAND (fresh state)`**: it points to a new state
directory for the next launch and is safe to copy verbatim. The state directory
must not already exist; a repeated path fails rather than overwriting evidence.
The retained ordinary resource helpers invoke **no pytest fixture** and no tests
run as part of manual startup; `pytest` supports the separate safety check below.
Those helpers live in `scripts/scrum45_support/` (process/resource lifecycle and
the manual database adapter), not in any E2E or service-integration fixture package.
The launcher resolves repository paths from its own file; an absolute launcher
path also works from another working directory. `--help` only parses arguments
and starts no services or containers.

All bindings are loopback and use generated ports; no normal development ports
are reserved or reused. Docker chooses its published database/broker ports.
API/Vite ports are selected dynamically with strict binding: a race causes
startup failure and owned cleanup rather than fallback to another port/stack.

### What startup creates

- Two uniquely named/labeled containers: one PostgreSQL, one RabbitMQ.
- Four separate owner databases: events, notifications, users, availability.
  Each receives **every unmodified SQL migration in filename order**, not a
  selected-schema approximation. Service ownership remains separate; only the
  synthetic fixture loader seeds each database's duplicate reference rows.
  Plain PostgreSQL is not hosted Supabase role/auth parity.
- Five Flask HTTP APIs, notification consumer, event-workflow dispatcher, and
  Vite: eight owned process groups. The Event Workflow HTTP composite is not
  needed; only its real dispatcher runs.
- Five synthetic users and four ready-to-act event fixtures, listed below.
- Logs and `state.json`, `fixtures.json`, `frontend-config.json`,
  `vite.config.mjs` in the printed state directory. `state.json` records exact
  URLs, owned container names/volume IDs/process-group IDs and cleanup status.

The server environments are allowlisted, with both Python/Flask dotenv loading
disabled. Vite uses `envDir: false`. Every frontend `VITE_*_URL` referenced in
source is explicitly set: either an isolated running API or one reserved,
non-listening local endpoint. Unsupported pages therefore fail locally instead
of falling back to shared services. Sandbox-only HTML transformation removes
remote font links; a CSP additionally restricts connections to the listed local
endpoints. No application API responses are mocked or intercepted.

## Ready fixtures and identities

Use the **Viewing as / Select active user** dropdown. This existing demo
identity mechanism replaces login; it is not proof of JWT authorization.

| User | Role / purpose |
| --- | --- |
| Synthetic Lead | Event Coordinator Lead; performs all four mutations |
| Synthetic Organiser | Owns all four events; receives SCRUM-45 notifications |
| Synthetic Coordinator One | Initial assignment target / old reassignment coordinator |
| Synthetic Coordinator Two | New reassignment coordinator |
| Synthetic Other Organiser | Unrelated identity for inbox isolation |

| Event | Initial state | Flow |
| --- | --- | --- |
| Community Workshop | Under Review; assigned to Synthetic Lead | Rejection |
| Approval Workshop | Under Review; assigned to Synthetic Lead | Approval |
| Assignment Workshop | Submitted; unassigned | Initial assignment |
| Reassignment Workshop | Under Review; assigned to Coordinator One | Reassignment |

Exact UUIDs live in `fixtures.json`; synthetic event dates are in 2030. There
is no need to submit an event, book equipment, or run those unrelated services.
All fixture inboxes start empty. No notifications are manufactured by seeding.

## Manual journeys and expected results

Use the printed UI base URL for all paths below. In all cases, delivery is
asynchronous: open `/notifications` as **Synthetic Organiser** and click
**Refresh notifications** until the expected row arrives (allow around 20
seconds before investigating logs). Opening **View details** in that row
marks it read, navigates to `/events/<fixture UUID>`, and decreases the unread
bell count. Do not expect coordinator inbox copies: SCRUM-45 targets the event
organiser, even when the message names the coordinator.

### 1. Rejection, inbox, and linked reason

1. Select **Synthetic Lead**; open `/requests/review` (**Request review** tab).
2. In the **Community Workshop** card—not Approval Workshop—click
   **Reject Request**.
3. Enter `Browser journey requires a safety plan.` and **Confirm rejection**.
4. Expect the **Event Request Rejected** dialog containing that exact reason;
   click **OK**.
5. Select **Synthetic Organiser**; open `/notifications`; refresh.
6. Expect `Community Workshop was rejected: Browser journey requires a safety plan.`
   and, if this is the first flow, a bell count of one unread.
7. Click the row's **View details**. Expect Community Workshop, **Rejected**,
   **Rejection reason**, the exact reason, and zero unread if no other work ran.

### 2. Approval

1. Select **Synthetic Lead**; open `/requests/review`.
2. In **Approval Workshop**, click **Approve Request**; expect
   **Event Request Approved** and close with **OK**.
3. As **Synthetic Organiser**, refresh `/notifications`.
4. Expect `Approval Workshop was approved`; open its **View details**.
5. Expect **Approval Workshop** with **Approved** status/decision.
   The unrelated registrations area is outside this minimal sandbox: its
   endpoint is intentionally unavailable. A registrations fetch warning does
   not establish notification failure; this runbook does not validate attendee
   registration behavior.

### 3. Initial coordinator assignment

1. Select **Synthetic Lead**; open `/requests/queue` (**Unassigned requests**).
2. In the **Assignment Workshop** row, choose **Synthetic Coordinator One**
   in **Coordinator**, then **Assign**.
3. Expect the success notice and the event to leave the unassigned queue.
4. As **Synthetic Organiser**, refresh `/notifications`.
5. Expect `Synthetic Coordinator One has been assigned to coordinate Assignment Workshop.`
6. Open that row; expect **Assignment Workshop** and **Synthetic Coordinator One**
   as its current coordinator. This goes through Coordinator Assignment
   Service's Lead/target-user validation, not a direct SQL edit.

### 4. Reassignment

1. Select **Synthetic Lead**; open `/requests/review`.
2. In **Reassignment Workshop**, click **Reassign Coordinator**.
3. Choose **Synthetic Coordinator Two** under **New coordinator** and click
   **Confirm Reassignment**.
4. Expect the reassignment success notice.
5. As **Synthetic Organiser**, refresh `/notifications`; expect
   `Synthetic Coordinator Two has been assigned to coordinate Reassignment Workshop.`
6. Open its row; expect **Reassignment Workshop** with Coordinator Two as the
   current coordinator. The event details may also show Coordinator One as
   assignment history; the new message must identify Coordinator Two.

### 5. Recipient isolation and read state

1. After the four flows, the organiser has four notifications. Opening each
   linked row makes all four read; the bell should show zero unread.
2. Select **Synthetic Other Organiser**, open `/notifications`, refresh.
   Expect **No notifications yet.**, no notification links, and no leaked
   organiser rows.
3. Repeat as Coordinator One and Coordinator Two: their inboxes are also empty
   for these organiser-targeted SCRUM-45 flows.
4. Switch back to Synthetic Organiser: the notifications and their read state
   remain. This checks identity-scoped UI/API state, not production auth.

## Stop, reset, and recover

Press **Ctrl-C once in the launcher terminal**. Wait for:

```text
CLEANUP {"status": "stopped", "failures": []}
```

Cleanup targets only the process groups and containers created by that launcher
instance. It removes the containers with their owned anonymous volumes and
reads back their absence, verifies process-group disappearance, and records
`status: stopped` / `cleanupFailures: []` in `state.json`. Logs remain.

**Every launch resets the data** by creating new containers/databases and
seeding these fixtures again. Stop before restarting; run the printed fresh
state command or the timestamped command above. Old evidence directories are
never treated as instructions to kill resources and are never overwritten.

Do not use `docker compose down`, Docker prune, shared migrations, broad
`pkill`, shared service restarts, or shared Supabase SQL for this sandbox.

SIGTERM also requests owned cleanup. SIGKILL, host shutdown, or Docker failure
can interrupt cleanup; no launcher can guarantee cleanup after those events.
If `cleanup-failed` is recorded, do not claim success. Inspect exact names,
volume IDs and process identities in that instance's state and ask for an
ownership-checked recovery; never signal stale recorded PIDs blindly.

## Automated launcher verification

From the tested root, fast helper tests (the Docker case is explicitly skipped):

```bash
uv run --no-project --with pytest --with httpx --with psycopg2-binary python -m pytest scripts/test_scrum45_manual_sandbox.py -q
```

All helper tests including owned Docker/API startup and SIGINT cleanup:

```bash
SCRUM45_RUN_MANUAL_TEST=1 uv run --no-project --with pytest --with httpx --with psycopg2-binary python -m pytest scripts/test_scrum45_manual_sandbox.py -q
```

The lifecycle case asserts health, all fixture event reads, a usable Lead queue,
loopback URLs, font-free HTML/CSP, a live launcher before interrupt, exact owned
process/container/volume disappearance afterward, and no cleanup diagnostics.
A separate real-process helper test deliberately fails setup, verifies owned
cleanup, preserves its error, and proves an unrelated bystander is untouched.

## Recorded execution and limits — October 24, 2026

Evidence is preserved outside the repository at:
`/Users/daphnetok/.hermes/cache/scratch/scrum45-manual-verification`.

- `pty-cleanup.json`, `pty-cli-session/`: the exact timestamped command above
  was also launched in a PTY, reached READY, stayed running for exploration,
  received a terminal Ctrl-C byte, and exited **0** with
  `CLEANUP {"status": "stopped", "failures": []}`. Independent reads verified
  all eight process groups, both containers and both owned volumes absent.
  `browser-sandbox-cleanup.json` separately records the browser-run cleanup.
  No verification sandbox was left running.
- `egress-cli-tests.log`: **5 passed**, including the actual container/API
  lifecycle test. RED/GREEN logs preserve the incremental configuration,
  lifecycle, CLI, fixture-status and external-asset guard checks.
- `browser.log`, `browser-requests.json`, `verify-browser.mjs`: unmocked,
  headless Playwright Chromium exercised **all four mutations through the UI**,
  organiser inbox delivery, read-on-open, all four linked detail pages, and
  unrelated/old/new coordinator inbox isolation. Final recorded browser run
  has no request/page errors and only loopback responses.
- `persisted-api-evidence.json`, `persisted-api.log`: independent HTTP rereads
  verify four saved outcomes, four read organiser inbox records (one rejection,
  one approval, two assignment messages), and empty inboxes for the other four
  synthetic identities. Six HTTP health endpoints returned 200.
- `01-rejection-linked-details.png`, `02-approval-linked-details.png`,
  `03-assignment-linked-details.png`, `05-reassignment-linked-details.png`, and
  `isolation-*.png`: final browser screenshots.
- Setup corrections are not concealed: the first assignment fixture incorrectly
  used Pending Review and was absent from the queue; a regression test and
  Submitted seed fixed it. An evidence script initially expected coordinator
  inbox copies, contrary to this organiser-only story; that assertion was
  corrected after checking the acceptance tests. Earlier HTML contacted Google
  Fonts for presentation assets; the sandbox now strips remote links and adds
  CSP, and the final run recorded no external requests. There were **no shared
  application API/database mutations**.
- The browser tool could not clone the running Chrome profile because its
  databases were locked. Verification used a fresh Playwright Chromium profile
  instead; existing Chrome and the unrelated manual stack were not stopped.

This verifies the listed SCRUM-45 happy-path user journeys in synthetic local
infrastructure. It does **not** prove production login/JWT behavior, hosted
Supabase grants/RLS, shared deployment readiness, attendee registrations,
full event submission, equipment/safety workflows, migration upgrade behavior,
or every failure/retry scenario. Those need their separately scoped suites and
review gates; this is not a claim that the entire application passes manual QA.

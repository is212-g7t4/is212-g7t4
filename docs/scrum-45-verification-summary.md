# SCRUM-45 verification summary

The implementation spec and ADR define the current acceptance criteria and ownership.
Automated coverage is consolidated into `test_scrum45_notifications.py` under each
owning service's unit and integration tiers (Event, Event Workflow, Notification).
Event additionally keeps full-chain clean/upgrade checks in `test_infra_migrations.py`.
The manual guide remains the shared-development handover; optional sandbox scripts
and their required support helpers are retained. Teammate-owned E2E is separate.

## Historical evidence

The five local task notes, eleven dated SCRUM-45 execution/review documents, and
five generated verification records (21 files) were archived outside the repository
before removal. They are not setup prerequisites. This removes historical records,
not production code, migrations, scripts or meaningful owner tests.

Recorded pre-sync automated run: Event 611, Workflow 118, Notification 97 unit tests;
Event 119, Workflow 22, Notification 17 service integration tests. These were tested
against the resolved, uncommitted older-main candidate, not the final latest-main
candidate. They are historical results, not a claim about a committed branch.

Manual results supplied by the user are user-reported, not independently repeated
by this automated cleanup. Read-only health/readiness smoke does not establish a new
approval, rejection, initial assignment or reassignment delivered to the inbox.
No shared-database mutation or migration is needed to run disposable integration
checks. Shared mutating manual confirmation remains an explicit handover gate.

## Latest-main candidate verification

The current filesystem incorporates fetched main `aee7bb0` while preserving the
original pending merge (`58f3986` + `eb41a2b`). No commit was created: latest-main
**content** integration is not a claim of completed Git merge ancestry. The original
dirty diagram override remains intact for final user review.

Automated rerun on this candidate: Event **629 unit / 125 integration**,
Workflow **118 / 25**, Notification **97 / 17** (844 unit, 167 integration).
Upstream withdrawal compatibility additionally passed Registration **47 / 3** and
Attendee Registration **46 / 4**. Frontend **809 Vitest + 4 Node** checks and the
TypeScript/Vite build passed. All existing coverage floors were retained; Event's
outbox is fully unit-covered. Optional sandbox safety: **4 passed, 1 explicit-opt-in
lifecycle skipped**; public Compose regression checks: **9 passed**.

The rejection-size regression first failed with HTTP 413 for ASCII, multibyte and
escaped reasons, then passed with an authenticated freeze-only **135,168-byte** cap.
Public mutations still have the **65,536-byte** cap. PostgreSQL checks cover exact
persisted reasons/envelopes through maximum accepted public bodies. Actual HTTPX /
Flask parsing independently accepted maximum-size and exact-cap envelopes and
refused over-cap/authentication failures. The worst escaped-name boundary measured
**134,522 bytes**, including a 32-character timestamp; the cap remains finite.
Integration assertion-sensitivity probes produced **9 expected assertion failures**,
not setup errors, then were restored and both complete tiers rerun green.

Dependency audits were not silently fixed: upstream root `concurrently` /
`shell-quote` report **2 critical** advisories; frontend Vitest tooling reports
**3 moderate** advisories. Frontend lint passed with 5 existing warnings. These
require separate dependency review; no CI changes or teammate E2E were made/run.

Shared-runtime handover and read-only health/config smoke do not replace manual
A–E confirmation. No shared migrations, resets or new acceptance events were run.

# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

Four roles, each with a distinct job in the same event lifecycle:

- **Event Organiser** — submits event requests (name, purpose, dates, expected attendance, venue/equipment/accessibility/registration requirements), tracks their own submissions ("My events"), views resulting event records.
- **Event Coordinator** — manages events assigned to them; can view the venue catalogue and venue details read-only to plan around them.
- **Venue Staff** — owns the venue catalogue (capacity, facilities, accessibility, layouts); reviews and approves/rejects venue booking requests, checking for scheduling conflicts.
- **Technical Support** — owns the equipment catalogue: adds equipment records and views the list of available equipment (built, via Equipment Service). Reviewing and approving/rejecting equipment reservation requests is planned; the reservation services are not yet built.

## Product Purpose

ConnectSphere coordinates the full lifecycle of organisational events: an organiser submits a request, it's checked against venue/equipment availability and conflicts, staff approve or reject it with a reason, and the organiser can track status through to a final event record. Success is a request reaching an unambiguous, conflict-free, auditable decision without manual cross-checking of venue/equipment schedules.

## Positioning

None — this is an academic project (IS212, Software Project Management) built and graded on process (Scrum/Jira traceability, sprints, tests, CI) and working software, not a competitive product. No market positioning claim should be invented; the product mechanism worth preserving is role-gated approval workflows backed by explicit conflict-checking (e.g. double-booking detection), not a business differentiator.

## Operating Context

- Monorepo: Flask microservices (`services/`, one per bounded concern, no shared library) + a React/TypeScript SPA (`frontend/event-management-ui/`), no API gateway — the UI calls composite/atomic services directly.
- Composites orchestrate atomics; atomics never call out. Notifications are the only async path (RabbitMQ), everything else synchronous REST/JSON.
- Currently built and visible in the UI: submitting an event request, viewing/managing submitted requests, reviewing requests, an event detail/record view, and a venue catalogue + venue detail view (read-only, gated to Event Coordinator and Venue Staff per SCRUM-24), and an equipment catalogue page where Technical Support can list equipment (filter by status, default Available) and add new records, including types not in the predefined list.
- Planned, not yet built: equipment reservation flow (the catalogue itself is built), notifications, forum/communication (clarifications and decision reasons), real authentication (Supabase Auth JWT issuance is not wired up yet — User Service is currently read-only).

## Capabilities and Constraints

- Role is read from User Service; if that service is down, role silently falls back to `Event Organiser`, which can make a permissions issue look like a role-gating bug — a known rough edge, not a feature.
- Venue catalogue and venue detail views are read-only and visible only to `Event Coordinator` and `Venue Staff` (`frontend/event-management-ui/src/features/venue/permissions.ts`); hidden from `Event Organiser` and `Technical Support`.
- No add/edit venue UI yet even for Venue Staff, and no suitability-check endpoint surfaced in the UI yet.
- Request statuses in the current data model: Pending, Submitted, Approved, Rejected.

## Brand Commitments

Product name: **ConnectSphere**. Visual direction: standard/canon path, played straight — restrained neutrals plus one accent, clean type, tight spacing, functional clarity, built to the craft level of **Linear, Notion, and Luma**, not a bespoke visual world. No invented aesthetic beyond matching that bar. Recorded 2026-10-01, scope: full frontend revamp.

## Evidence on Hand

No real content, sample data, testimonials, or case studies exist. `src/mockData.ts` holds placeholder data for local development only — future work must not treat it as evidence of real usage patterns and must not fabricate testimonials, customer names, or benchmarks.

## Product Principles

1. Every cross-resource decision (venue/equipment booking) must be conflict-checked before it's presented as available — never let the UI imply availability the backend hasn't verified.
2. Role gates are a first-class UX concern, not just an API concern: what a role can't do should be invisible or clearly explained, not silently broken.
3. Status must always be traceable: an organiser should be able to see where a request stands (pending/approved/rejected) and, once built, why.
4. Keep scope traceable to what's actually built (see the "planned" vs "built" distinction in INDEX.md) — don't design UI for services that don't exist yet without flagging it as forward-looking.

## Accessibility & Inclusion

No formal accessibility standard has been established yet. Note: the event request form already collects "accessibility needs" as event data (a product feature), which is distinct from the UI's own accessibility compliance — no requirement confirmed for the latter.

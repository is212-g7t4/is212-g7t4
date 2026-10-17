# event-workflow-service

Composite service (port **5014**) for SCRUM-20, *update event information
during planning*. It sits between the UI and Event Service on
`PATCH /events/<id>/details`:

1. The caller must be the event's assigned coordinator, or the Event
   Coordinator Lead when the event has no assigned coordinator (role looked
   up in User Service).
2. Event Service classifies the edit as low- or high-impact with nothing
   written (`dryRun`). It stays the single authority on that split.
3. A high-impact edit is checked against the event's other arrangements. Any
   contradiction refuses it with `409 CHANGE_CONTRADICTS_ARRANGEMENTS` and a
   list of reasons; nothing is saved.
4. Otherwise Event Service saves it. A high-impact edit of a `Confirmed` event
   still comes back `409 SAFETY_RECHECK_REQUIRED`, so the safety re-check
   (SCRUM-153) is only offered after this validation has passed.

## Contradiction rules

| Change | Contradiction |
|---|---|
| Start/end date | The event has live (not Cancelled/Expired/Rejected) venue bookings and none overlaps the new window |
| Start/end date | A Pending/Approved equipment line exceeds stock available in the new window (total less Approved lines of other overlapping events) |
| Attendance increased | New attendance exceeds the catalogue capacity of a venue with a live booking |

Venue requirements, accessibility needs and the free-text equipment
requirements have no rule. If a downstream service can't be read, the edit is
refused (fail closed).

## Run

```
uv sync
uv run flask --app app run --debug
uv run pytest
```

Calls: Event, User, Venue Availability, Venue, Equipment Request, Equipment.

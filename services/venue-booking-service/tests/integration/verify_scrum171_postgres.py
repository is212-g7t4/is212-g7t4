"""# Test scope and acceptance mapping — SCRUM-171 integration

- **Real HTTP → owned PostgreSQL:** direct data-level AC1/AC2/AC5 plus AC3/AC4 API support; named case sections below distinguish exact clauses from infrastructure and separately approved immutability.
- **Scope:** automatic setup/teardown, UUID database, loopback-only ports and synthetic fixtures. Counts are checks, not unique acceptance cases; no browser display proof.

## Case/group traceability

The named test functions/cases below implement the groups above; their existing
names and assertions specify the scenario. No group is credited with all five ACs.

## Existing test contract and detailed cases

SCRUM-171 opt-in HTTP/PostgreSQL test. No shared targets or frontend.
Run with venue-availability-service/.venv/bin/python; --output must be new.
Only synthetic data in a UUID Docker container. All owned resources removed in finally.

Canonical SCRUM-171 acceptance criteria (approved five-criterion set):
AC1: Given a venue closure is confirmed, when it is recorded, then all requests for that venue with booking periods that overlap the closure and a status of Pending, Pending Review, or Approved are changed to Rejected.
AC2: Given a closure is recorded, then the event itself and all venue requests that do not meet the rejection conditions in AC1 remain unchanged, including requests under the same event. Requests ending exactly when the closure starts, or starting exactly when it ends, are not considered overlapping.
AC3: Given a request was rejected because of a closure, when an authorised user views its details, then the system shows that the closure caused the rejection, the full closure period in Singapore time, and the operational reason.
AC4: Given a Venue Staff member submits a closure, then the system shows the closure details and the number and list of affected requests, including their events, venues, booking periods and statuses, before asking for confirmation. If the affected requests change before the closure is saved, the staff member must review and confirm the updated list. Going back or cancelling before saving makes no changes.
AC5: Given a Venue Staff member confirms a closure, then the closure and all affected rejections are saved together. If the system cannot complete the operation, neither the closure nor any of those rejections is saved.

Traceability uses existing check names/IDs; predicates and execution order stay
unchanged. These HTTP/database checks do not prove user-facing display:
- atomic_closure_and_rejections: AC1 (including independently affected siblings),
  with successful-save support for AC5; rollback_*: AC5 failure atomicity.
- unaffected_and_parent_preserved: AC2, including half-open boundary fixtures.
- persisted_metadata_through_composite: AC3 data/API support only.
- read_only_complete_preview, composite_complete_named_preview,
  complete_preview_more_than_100_requests: AC4 backend preview support.
- zero_to_one_requires_refreshed_confirmation, changed_* and
  postgres_gate_wait_rechecks_changed_impact: AC4 reconfirmation support.
- migration_preserves_existing_manual_rejection: migration/legacy regression;
  automatic_rejection_preserves_reviewer_and_all_other_fields: affected-row
  metadata preservation support, not direct AC2 unaffected-row evidence.
- closure_and_booking_lock_order_no_deadlock: cross-ticket concurrency support;
  existing_window_keeps_closure_and_excludes_rejected: calendar regression.
- immutable_* and replacement_uses_existing_create_flow: separately approved
  immutability/replacement business rule, not an additional acceptance criterion.
Other validation, transport, infrastructure and contract checks are supporting
checks, not standalone proof of an entire canonical acceptance criterion.
"""

import argparse
import hashlib
import json
import os
from pathlib import Path
import socket
import subprocess
import time
import traceback
from datetime import datetime, timedelta
from urllib.request import Request, urlopen
from urllib.error import HTTPError
from uuid import uuid4
from zoneinfo import ZoneInfo
import psycopg2
from psycopg2.extras import RealDictCursor

ROOT = Path(__file__).resolve().parents[4]
MIGRATION = (
    ROOT / "database/supabase/migrations/20261016000000_booking_closure_rejection.sql"
)


def cmd(*args):
    return subprocess.check_output(args, text=True, stderr=subprocess.STDOUT).strip()


def port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def http(url, data=None, headers=None, method=None):
    req = Request(
        url,
        data=json.dumps(data).encode() if data is not None else None,
        headers={"Content-Type": "application/json", **(headers or {})},
        method=method,
    )
    try:
        response = urlopen(req, timeout=20)
    except HTTPError as error:
        response = error
    with response:
        return response.status, json.load(response)


class Harness:
    def __init__(self, output):
        output.mkdir(parents=True, exist_ok=False)
        self.out = output
        self.name = "scrum171-" + uuid4().hex
        self.processes, self.logs = [], []
        self.created = False
        self.connection = None
        self.ports = {}
        self.report = dict(
            marker=self.name,
            cases=[],
            startedAt=datetime.now().astimezone().isoformat(),
        )

    def sql(self, query, params=()):
        assert self.connection.info.host == "127.0.0.1"
        assert self.connection.info.port == self.dbport
        assert self.connection.info.dbname == self.name
        with self.connection.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(query, params)
            return [dict(r) for r in cur.fetchall()] if cur.description else []

    def setup(self):
        self.report["head"] = cmd("git", "-C", str(ROOT), "rev-parse", "HEAD")
        self.report["sources"] = {
            str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
            for service in ("venue-availability", "venue-booking", "venue", "event")
            for p in (ROOT / f"services/{service}-service/app").glob("*.py")
        }
        cmd(
            "docker",
            "run",
            "-d",
            "--name",
            self.name,
            "--label",
            "scrum171=owned",
            "-e",
            "POSTGRES_HOST_AUTH_METHOD=trust",
            "-e",
            "POSTGRES_DB=" + self.name,
            "-p",
            "127.0.0.1::5432",
            "postgres:16",
        )
        self.created = True
        self.dbport = int(
            cmd("docker", "port", self.name, "5432/tcp").rsplit(":", 1)[1]
        )
        self.dsn = f"host=127.0.0.1 port={self.dbport} dbname={self.name} user=postgres"
        for _ in range(100):
            try:
                self.connection = psycopg2.connect(self.dsn, connect_timeout=1)
                break
            except psycopg2.OperationalError:
                time.sleep(0.1)
        assert self.connection is not None
        self.connection.autocommit = True
        self.report["database"] = dict(
            host="127.0.0.1",
            port=self.dbport,
            name=self.name,
            version=self.sql("SELECT version() AS v")[0]["v"],
        )
        for p in sorted((ROOT / "database/supabase/migrations").glob("*.sql")):
            if p != MIGRATION:
                self.sql(p.read_text())
        self.ids = {
            k: str(uuid4())
            for k in ["staff", "coordinator", "organiser", "event", "venue", "other"]
        }
        for role in ["staff", "coordinator", "organiser"]:
            self.sql(
                'INSERT INTO public."User" (user_id,username,email,role) VALUES (%s,%s,%s,%s)',
                (
                    self.ids[role],
                    self.name + role,
                    self.name + role + "@example.invalid",
                    {
                        "staff": "Venue Staff",
                        "coordinator": "Event Coordinator",
                        "organiser": "Event Organiser",
                    }[role],
                ),
            )
        self.base = datetime.now(ZoneInfo("Asia/Singapore")).replace(microsecond=0)
        self.sql(
            'INSERT INTO public."Event" (event_id,event_name,status,organiser_id,coordinator_id,expected_attendance,preferred_start_date,preferred_end_date) VALUES (%s,%s,%s,%s,%s,20,%s,%s)',
            (
                self.ids["event"],
                self.name,
                "Under Review",
                self.ids["organiser"],
                self.ids["coordinator"],
                self.stamp(-48),
                self.stamp(240),
            ),
        )
        for v in ["venue", "other"]:
            self.sql(
                'INSERT INTO public."Venue" (venue_id,venue_name,location,max_capacity,facilities,supported_layouts,operational_status) VALUES (%s,%s,%s,100,%s,%s,%s)',
                (self.ids[v], self.name + v, "synthetic", "[]", "[]", "Available"),
            )
        self.legacy = self.booking("Rejected", 10, 12)
        self.sql(
            'UPDATE public."VenueBooking" SET rejection_reason=%s WHERE booking_id=%s',
            ("Existing manual reason", self.legacy),
        )
        self.report["fixtureIds"] = self.ids

    def stamp(self, hours):
        return self.base + timedelta(hours=hours)

    def booking(self, status, start, end, venue="venue"):
        bid = str(uuid4())
        self.sql(
            'INSERT INTO public."VenueBooking" (booking_id,event_id,venue_id,requested_start_time,requested_end_time,required_capacity,venue_requirements,status,requested_by,reviewed_by) VALUES (%s,%s,%s,%s,%s,20,%s,%s,%s,%s)',
            (
                bid,
                self.ids["event"],
                self.ids[venue],
                self.stamp(start),
                self.stamp(end),
                "synthetic",
                status,
                self.ids["coordinator"],
                self.ids["staff"],
            ),
        )
        return bid

    def snapshot(self):
        return {
            table: self.sql(f'SELECT * FROM public."{table}" ORDER BY 1')
            for table in ["VenueBooking", "VenueClosure", "Event"]
        }

    def check(self, name, condition, **evidence):
        self.report["cases"].append(dict(name=name, passed=bool(condition), **evidence))
        assert condition, name

    def services(self):
        self.ports = {
            s: port() for s in ["event", "venue", "venue-availability", "venue-booking"]
        }
        env = {
            **os.environ,
            "DATABASE_URL": self.dsn,
            "PYTHON_DOTENV_DISABLED": "1",
            "FLASK_SKIP_DOTENV": "1",
            "FLASK_DEBUG": "0",
            "CALENDAR_DEV_MODE": "true",
            "VENUE_CLOSURE_DEV_MODE": "true",
            "CLOSURE_CONFIRMATION_KEY": uuid4().hex + uuid4().hex,
            **{
                s.upper().replace("-", "_") + "_SERVICE_URL": f"http://127.0.0.1:{p}"
                for s, p in self.ports.items()
            },
        }
        for service, p in self.ports.items():
            directory = ROOT / f"services/{service}-service"
            log = (self.out / (service + ".log")).open("w")
            self.logs.append(log)
            proc = subprocess.Popen(
                [
                    str(directory / ".venv/bin/python"),
                    "-m",
                    "flask",
                    "--app",
                    "app",
                    "run",
                    "--host",
                    "127.0.0.1",
                    "--port",
                    str(p),
                    "--no-reload",
                ],
                cwd=directory,
                env=env,
                stdout=log,
                stderr=subprocess.STDOUT,
            )
            self.processes.append(proc)
            for _ in range(100):
                assert proc.poll() is None, service + " startup failed"
                try:
                    if http(self.url(service, "/health"))[0] == 200:
                        break
                except OSError:
                    pass
                time.sleep(0.1)
            else:
                raise AssertionError(service + " health timeout")

    def url(self, service, path):
        return f"http://127.0.0.1:{self.ports[service]}" + path

    def closure(self, start=10, end=12):
        return dict(
            venueId=self.ids["venue"],
            startDateTime=self.stamp(start).isoformat(),
            endDateTime=self.stamp(end).isoformat(),
            reason="Maintenance\n<script>plain text</script>",
        )

    @property
    def headers(self):
        return {"X-Dev-User-Id": self.ids["staff"], "X-Dev-Role": "Venue Staff"}

    def teardown(self):
        if self.connection:
            try:
                self.report["reconciled"] = self.snapshot()
            except Exception:
                self.report["reconciliationError"] = traceback.format_exc()
            self.connection.close()
        for p in self.processes:
            p.terminate()
        for p in self.processes:
            try:
                p.wait(timeout=10)
            except subprocess.TimeoutExpired:
                p.kill()
                p.wait(timeout=10)
        for log in self.logs:
            log.close()
        if self.created:
            cmd("docker", "rm", "-f", "-v", self.name)
            self.report["containerAbsent"] = not cmd(
                "docker",
                "ps",
                "-a",
                "--filter",
                "name=^/" + self.name + "$",
                "--format",
                "{{.ID}}",
            )
        self.report["portsClosed"] = {}
        for name, p in {**self.ports, "postgres": getattr(self, "dbport", 0)}.items():
            if p:
                with socket.socket() as s:
                    self.report["portsClosed"][name] = (
                        s.connect_ex(("127.0.0.1", p)) != 0
                    )
        self.report["finishedAt"] = datetime.now().astimezone().isoformat()
        (self.out / "evidence.json").write_text(
            json.dumps(self.report, indent=2, default=str)
        )


def cases(h):
    before = h.snapshot()
    h.check("migration_prepared", MIGRATION.exists())
    h.sql(MIGRATION.read_text())
    after = h.snapshot()
    old = before["VenueBooking"][0]
    new = after["VenueBooking"][0]
    h.check(
        "migration_preserves_existing_manual_rejection",
        all(new[k] == v for k, v in old.items())
        and new["rejection_closure_id"] is None,
        before=before,
        after=after,
        migrationSha256=hashlib.sha256(MIGRATION.read_bytes()).hexdigest(),
    )

    affected = [
        h.booking(status, 9, 13) for status in ["Pending", "Pending Review", "Approved"]
    ]
    unchanged = [
        h.booking(status, 10, 12)
        for status in ["Rejected", "Cancelled", "Expired", "On Hold"]
    ]
    unchanged += [
        h.booking("Approved", 8, 10),
        h.booking("Approved", 12, 14),
        h.booking("Approved", 10, 12, "other"),
    ]
    before = h.snapshot()
    h.services()
    body = h.closure()
    url = h.url("venue-availability", "/venue-closures")
    status, preview = http(url + "/preview", body, h.headers)
    h.check(
        "read_only_complete_preview",
        status == 200 and preview.get("affectedCount") == 3 and h.snapshot() == before,
        status=status,
        response=preview,
    )
    status, result = http(
        url,
        body | {"confirmed": True, "confirmationToken": preview["confirmationToken"]},
        h.headers,
    )
    after = h.snapshot()
    by_id = {r["booking_id"]: r for r in after["VenueBooking"]}
    h.check(
        "atomic_closure_and_rejections",
        status == 201
        and result.get("rejectedCount") == 3
        and all(
            by_id[b]["status"] == "Rejected"
            and by_id[b]["rejection_closure_reason"] == body["reason"]
            for b in affected
        ),
        status=status,
        response=result,
        before=before,
        after=after,
    )
    h.check(
        "unaffected_and_parent_preserved",
        before["Event"] == after["Event"]
        and all(
            r == by_id[r["booking_id"]]
            for r in before["VenueBooking"]
            if r["booking_id"] not in affected
        ),
    )

    allowed = {
        "status",
        "rejection_closure_id",
        "rejection_closure_start",
        "rejection_closure_end",
        "rejection_closure_reason",
        "rejected_at",
    }
    h.check(
        "automatic_rejection_preserves_reviewer_and_all_other_fields",
        all(
            all(
                by_id[row["booking_id"]][key] == value
                for key, value in row.items()
                if key not in allowed
            )
            for row in before["VenueBooking"]
            if row["booking_id"] in affected
        ),
    )

    # Read metadata through both HTTP layers; legacy reason is not invented.
    status, detail = http(
        h.url(
            "venue-booking",
            f'/events/{h.ids["event"]}/booking-requests?coordinatorId={h.ids["coordinator"]}',
        )
    )
    details = {r["id"]: r for r in detail.get("bookings", [])}
    h.check(
        "persisted_metadata_through_composite",
        status == 200
        and details[h.legacy]["closureRejection"] is None
        and all(
            details[b]["closureRejection"]["reason"] == body["reason"]
            and details[b]["closureRejection"]["startDateTime"] == body["startDateTime"]
            for b in affected
        ),
        response=detail,
    )
    mutation = dict(
        eventId=h.ids["event"],
        venueId=h.ids["venue"],
        coordinatorId=h.ids["coordinator"],
        reviewedBy=h.ids["staff"],
        requestedStartTime=h.stamp(80).replace(tzinfo=None).isoformat(),
        requestedEndTime=h.stamp(81).replace(tzinfo=None).isoformat(),
        requiredCapacity=20,
        venueRequirements="replacement",
    )
    for service, prefix in [
        ("venue-availability", "/venue-bookings/"),
        ("venue-booking", "/booking-requests/"),
    ]:
        for bid in [h.legacy, affected[0]]:
            for action in ["", "/cancel", "/approve", "/reject"]:
                before = h.snapshot()
                status, result = http(
                    h.url(service, prefix + bid + action), mutation, method="PATCH"
                )
                h.check(
                    "immutable_" + service + "_" + bid + action,
                    status == 409
                    and result.get("code") == "BOOKING_IMMUTABLE"
                    and h.snapshot() == before,
                    status=status,
                    response=result,
                )
    before = h.snapshot()
    status, result = http(h.url("venue-booking", "/booking-requests"), mutation)
    after = h.snapshot()
    h.check(
        "replacement_uses_existing_create_flow",
        status == 201
        and result.get("status") == "Pending Review"
        and result.get("id") not in by_id
        and before["Event"] == after["Event"]
        and all(r in after["VenueBooking"] for r in before["VenueBooking"]),
        status=status,
        response=result,
    )

    composite = h.url("venue-booking", "/venue-closures")
    # Ongoing, overnight and containment/partial overlaps under the same parent.
    shapes = [(-2, 2), (19, 21), (20, 22), (21, 25), (19, 25), (20.5, 21), (23, 50)]
    shape_ids = [h.booking("Approved", start, end) for start, end in shapes]
    body = h.closure(-1, 24)
    before = h.snapshot()
    status, preview = http(composite + "/preview", body, h.headers)
    expected = [
        r["booking_id"]
        for r in before["VenueBooking"]
        if r["venue_id"] == h.ids["venue"]
        and r["status"] in ["Pending", "Pending Review", "Approved"]
        and r["requested_start_time"] < h.stamp(24)
        and r["requested_end_time"] > h.stamp(-1)
    ]
    h.check(
        "composite_complete_named_preview",
        status == 200
        and {r["id"] for r in preview.get("affectedRequests", [])} == set(expected)
        and all(
            r["eventName"] == h.name and r["venueName"] == h.name + "venue"
            for r in preview["affectedRequests"]
        )
        and before == h.snapshot(),
        status=status,
        response=preview,
    )
    status, result = http(
        composite,
        body | dict(confirmed=True, confirmationToken=preview["confirmationToken"]),
        h.headers,
    )
    after = h.snapshot()
    h.check(
        "ongoing_overnight_all_overlap_shapes",
        status == 201
        and result.get("rejectedCount") == len(expected)
        and all(
            r["status"] == "Rejected"
            for r in after["VenueBooking"]
            if r["booking_id"] in shape_ids
        ),
        status=status,
        response=result,
    )

    # Confirmations cannot be substituted or supplied with client IDs/counts.
    body = h.closure(30, 32)
    status, preview = http(composite + "/preview", body, h.headers)
    h.check(
        "zero_impact_preview",
        status == 200
        and preview["affectedRequests"] == []
        and preview["affectedCount"] == 0,
    )
    confirmation = dict(confirmed=True, confirmationToken=preview["confirmationToken"])
    for name, payload, headers, expected_status in [
        ("missing_confirmation", body, h.headers, 400),
        (
            "false_confirmation",
            body | confirmation | {"confirmed": False},
            h.headers,
            400,
        ),
        (
            "tampered_token",
            body | confirmation | {"confirmationToken": "tampered"},
            h.headers,
            409,
        ),
        ("different_reason", body | confirmation | {"reason": "other"}, h.headers, 409),
        (
            "different_period",
            body | confirmation | {"endDateTime": h.stamp(33).isoformat()},
            h.headers,
            409,
        ),
        (
            "different_staff",
            body | confirmation,
            h.headers | {"X-Dev-User-Id": h.ids["coordinator"]},
            409,
        ),
        (
            "client_ids_not_trusted",
            body | confirmation | {"affectedRequests": [], "affectedCount": 0},
            h.headers,
            400,
        ),
        (
            "wrong_role",
            body | confirmation,
            h.headers | {"X-Dev-Role": "Event Coordinator"},
            403,
        ),
    ]:
        before = h.snapshot()
        status, result = http(composite, payload, headers)
        h.check(
            name,
            status == expected_status and before == h.snapshot(),
            status=status,
            response=result,
        )
    bid = h.booking("Pending", 30, 32)
    before = h.snapshot()
    status, result = http(composite, body | confirmation, h.headers)
    h.check(
        "zero_to_one_requires_refreshed_confirmation",
        status == 409
        and result.get("code") == "CLOSURE_PREVIEW_CHANGED"
        and before == h.snapshot(),
        status=status,
        response=result,
    )
    for field, value in [
        ("status", "Approved"),
        ("requested_start_time", h.stamp(29)),
        ("requested_end_time", h.stamp(33)),
        ("status", "Cancelled"),
    ]:
        _, preview = http(composite + "/preview", body, h.headers)
        h.sql(
            f'UPDATE public."VenueBooking" SET {field}=%s WHERE booking_id=%s',
            (value, bid),
        )
        before = h.snapshot()
        status, result = http(
            composite,
            body | dict(confirmed=True, confirmationToken=preview["confirmationToken"]),
            h.headers,
        )
        h.check(
            "changed_" + field + "_" + str(value),
            status == 409
            and result.get("code") == "CLOSURE_PREVIEW_CHANGED"
            and before == h.snapshot(),
            status=status,
            response=result,
        )
    _, preview = http(composite + "/preview", body, h.headers)
    status, result = http(
        composite,
        body | dict(confirmed=True, confirmationToken=preview["confirmationToken"]),
        h.headers,
    )
    h.check(
        "fresh_zero_impact_confirmation_succeeds",
        status == 201 and result.get("rejectedCount") == 0,
        status=status,
        response=result,
    )

    # SQL trigger failures prove real transaction rollback, not mocked commit calls.
    h.booking("Approved", 40, 42)
    h.booking("Pending Review", 40, 42)
    body = h.closure(40, 42)
    for table, action in [("VenueClosure", "INSERT"), ("VenueBooking", "UPDATE")]:
        h.sql(
            "CREATE OR REPLACE FUNCTION fail_scrum171() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'injected test failure'; END $$"
        )
        if table == "VenueBooking":
            h.sql("CREATE SEQUENCE failure_counter")
            h.sql(
                "CREATE OR REPLACE FUNCTION fail_scrum171() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN IF nextval('failure_counter') = 2 THEN RAISE EXCEPTION 'injected after first booking update'; END IF; RETURN NEW; END $$"
            )
        h.sql(
            f'CREATE TRIGGER fail_scrum171 BEFORE {action} ON public."{table}" FOR EACH ROW EXECUTE FUNCTION fail_scrum171()'
        )
        _, preview = http(composite + "/preview", body, h.headers)
        before = h.snapshot()
        status, result = http(
            composite,
            body | dict(confirmed=True, confirmationToken=preview["confirmationToken"]),
            h.headers,
        )
        h.check(
            "rollback_" + table,
            status == 503 and before == h.snapshot(),
            status=status,
            response=result,
            before=before,
            after=h.snapshot(),
        )
        if table == "VenueBooking":
            h.check(
                "rollback_after_first_booking_was_updated",
                h.sql("SELECT last_value FROM failure_counter")[0]["last_value"] == 2,
            )
        h.sql(f'DROP TRIGGER fail_scrum171 ON public."{table}"')
    _, preview = http(composite + "/preview", body, h.headers)
    status, result = http(
        composite,
        body | dict(confirmed=True, confirmationToken=preview["confirmationToken"]),
        h.headers,
    )
    h.check(
        "success_after_rollback",
        status == 201 and result.get("rejectedCount") == 2,
        status=status,
        response=result,
    )

    # Real lock wait: a committed change after preview is rechecked under gate.
    import threading

    body = h.closure(60, 62)
    race_id = h.booking("Pending", 60, 62)
    _, preview = http(composite + "/preview", body, h.headers)
    blocker = psycopg2.connect(h.dsn)
    results = []
    try:
        with blocker.cursor() as cur:
            cur.execute("SELECT pg_advisory_xact_lock(171, 1)")
            cur.execute(
                'UPDATE public."VenueBooking" SET status=%s WHERE booking_id=%s',
                ("Approved", race_id),
            )
        worker = threading.Thread(
            target=lambda: results.append(
                http(
                    composite,
                    body
                    | dict(
                        confirmed=True, confirmationToken=preview["confirmationToken"]
                    ),
                    h.headers,
                )
            )
        )
        worker.start()
        waits = []
        for _ in range(100):
            waits = h.sql(
                "SELECT wait_event_type,wait_event,query FROM pg_stat_activity WHERE datname=current_database() AND wait_event_type='Lock'"
            )
            if waits:
                break
            time.sleep(0.02)
        blocker.commit()
        worker.join(25)
        status, result = results[0] if results else (None, {})
        h.check(
            "postgres_gate_wait_rechecks_changed_impact",
            bool(waits)
            and status == 409
            and result.get("code") == "CLOSURE_PREVIEW_CHANGED",
            waits=waits,
            status=status,
            response=result,
        )
        h.check(
            "concurrent_fixture_only_no_closure_write",
            not any(
                r["start_date_time"] == h.stamp(60)
                for r in h.snapshot()["VenueClosure"]
            ),
        )
    finally:
        blocker.close()

    # Closure owns gate while waiting on the established venue-row lock.
    # A booking writer cannot take the reverse row-lock order ahead of it.
    body = h.closure(90, 92)
    _, preview = http(composite + "/preview", body, h.headers)
    blocker = psycopg2.connect(h.dsn)
    results = []
    booking_results = []
    try:
        with blocker.cursor() as cur:
            cur.execute(
                'SELECT venue_id FROM public."Venue" WHERE venue_id=%s FOR UPDATE',
                (h.ids["venue"],),
            )
        closer = threading.Thread(
            target=lambda: results.append(
                http(
                    composite,
                    body
                    | dict(
                        confirmed=True, confirmationToken=preview["confirmationToken"]
                    ),
                    h.headers,
                )
            )
        )
        closer.start()
        for _ in range(100):
            waits = h.sql(
                "SELECT wait_event_type,wait_event,query FROM pg_stat_activity WHERE datname=current_database() AND wait_event_type='Lock'"
            )
            if any("Venue" in r["query"] for r in waits):
                break
            time.sleep(0.02)
        racing_payload = mutation | dict(
            requestedStartTime=h.stamp(90).replace(tzinfo=None).isoformat(),
            requestedEndTime=h.stamp(92).replace(tzinfo=None).isoformat(),
        )
        writer = threading.Thread(
            target=lambda: booking_results.append(
                http(h.url("venue-booking", "/booking-requests"), racing_payload)
            )
        )
        writer.start()
        for _ in range(100):
            waits = h.sql(
                "SELECT wait_event_type,wait_event,query FROM pg_stat_activity WHERE datname=current_database() AND wait_event_type='Lock'"
            )
            if len(waits) >= 2:
                break
            time.sleep(0.02)
        blocker.commit()
        closer.join(25)
        writer.join(25)
        h.check(
            "closure_and_booking_lock_order_no_deadlock",
            len(waits) >= 2
            and results[0][0] == 201
            and booking_results[0][0] == 409
            and booking_results[0][1].get("conflictTypes") == ["VENUE_CLOSURE"],
            waits=waits,
            closure=results,
            booking=booking_results,
        )
    finally:
        blocker.close()

    # All impact rows beyond a conventional page size survive the HTTP preview.
    bulk = [h.booking("Pending Review", 100, 102) for _ in range(105)]
    body = h.closure(100, 102)
    before = h.snapshot()
    status, preview = http(composite + "/preview", body, h.headers)
    h.check(
        "complete_preview_more_than_100_requests",
        status == 200
        and {r["id"] for r in preview["affectedRequests"]} == set(bulk)
        and preview["affectedCount"] == 105
        and before == h.snapshot(),
        status=status,
        response=preview,
    )
    # Missing name is an upstream integrity failure, not permission to confirm a partial list.
    h.sql(
        'UPDATE public."Event" SET event_name=NULL WHERE event_id=%s', (h.ids["event"],)
    )
    before = h.snapshot()
    status, result = http(composite + "/preview", body, h.headers)
    h.check(
        "preview_missing_event_name_fails_closed",
        status == 502 and before == h.snapshot() and "confirmationToken" not in result,
        status=status,
        response=result,
    )
    h.sql(
        'UPDATE public."Event" SET event_name=%s WHERE event_id=%s',
        (h.name, h.ids["event"]),
    )

    utc_id = h.booking("Pending", 110, 112)
    body = h.closure(110, 112)
    body["startDateTime"] = h.stamp(110).astimezone(ZoneInfo("UTC")).isoformat()
    body["endDateTime"] = h.stamp(112).astimezone(ZoneInfo("UTC")).isoformat()
    status, preview = http(composite + "/preview", body, h.headers)
    h.check(
        "explicit_utc_input_matches_singapore_booking",
        status == 200 and [r["id"] for r in preview["affectedRequests"]] == [utc_id],
        status=status,
        response=preview,
    )
    status, result = http(
        composite,
        body | dict(confirmed=True, confirmationToken=preview["confirmationToken"]),
        h.headers,
    )
    cid = result["closure"]["closureId"]
    h.check(
        "closure_saved_with_singapore_output",
        status == 201
        and result["closure"]["startDateTime"] == h.stamp(110).isoformat(),
        status=status,
        response=result,
    )
    status, detail = http(composite + "/" + cid, headers=h.headers)
    h.check(
        "existing_closure_detail_contract",
        status == 200 and detail["closure"] == result["closure"],
        response=detail,
    )
    from urllib.parse import urlencode

    status, listing = http(
        composite + "?" + urlencode({"venueId": h.ids["venue"], "limit": 1}),
        headers=h.headers,
    )
    h.check(
        "existing_closure_pagination_contract",
        status == 200 and len(listing["closures"]) == 1 and listing["nextCursor"],
        response=listing,
    )
    query = urlencode(
        {"dateFrom": h.stamp(109).isoformat(), "dateTo": h.stamp(113).isoformat()}
    )
    status, window = http(
        h.url("venue-availability", "/venue-bookings/window?") + query
    )
    h.check(
        "existing_window_keeps_closure_and_excludes_rejected",
        status == 200
        and any(c["closureId"] == cid for c in window["closures"])
        and not any(r["id"] == utc_id for r in window["bookings"]),
        response=window,
    )


def main(out):
    h = Harness(out)
    try:
        h.setup()
        cases(h)
    except Exception:
        h.report["failure"] = traceback.format_exc()
    finally:
        h.teardown()
    print(
        json.dumps(
            {
                "evidence": str(out / "evidence.json"),
                "cases": len(h.report["cases"]),
                "failure": h.report.get("failure"),
                "cleanup": h.report.get("containerAbsent"),
            }
        )
    )
    return int(
        "failure" in h.report
        or not h.report.get("containerAbsent")
        or not all(h.report["portsClosed"].values())
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    raise SystemExit(main(parser.parse_args().output.resolve()))

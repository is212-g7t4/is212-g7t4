"""# SCRUM-173 — Receive Venue Disruption Notifications

As an Event Coordinator, I want to receive an in-app notification when a venue booking for an event assigned to me is affected, so that I know that alternative arrangements are required.
AC1: Given a rejection is ready for notification, then the notification is addressed to the coordinator assigned to that event when the notification is created.
AC2: The notification contains the event name, affected venue, closure start/end, rejection reason, and a link to the venue rejection.
AC3: Given a temporary system failure occurs during notification dispatch, the system must ensure the notification is eventually delivered to the assigned coordinator without generating multiple duplicate alerts.

## Layer and scope
# SCRUM-173 backend-only real HTTP/PostgreSQL/RabbitMQ verification.
AC1: preparation assignment and immutable recipient. AC2: exact complete content.
AC3: outbox atomicity, outage/lease recovery, unknown publish/ack, dedup/read state.
Infrastructure owns UUID-named containers, all databases, ports and processes.
Run: uv run --with psycopg2-binary python tests/integration/verify_scrum173_backend.py --evidence /absolute/path
No .env is read; all service environment settings are pinned to synthetic values.


## AC groups
AC1: current coordinator at preparation; recipient frozen across retries.
AC2: complete frozen content and structured rejection destination.
AC3: eventual delivery without duplicate inbox alerts.
Security, diagnostics, process adapters, fixtures and legacy compatibility are
explicit supporting/cross-ticket checks, not separate direct AC scenarios.
FIRST: unit I/O/clocks are mocked; real integration owns setup/finally teardown.
Historical tests are retrospective evidence, not a blanket test-first claim.
"""

import argparse
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import time
from uuid import uuid4
import urllib.request
import urllib.error
import psycopg2

ROOT = Path(__file__).resolve().parents[4]
TOKEN = "scrum173-isolated-test-token-not-production"
KEY = "scrum173-isolated-preview-key-not-production"
A = "10000000-0000-0000-0000-000000000001"
B = "10000000-0000-0000-0000-000000000002"
C = "10000000-0000-0000-0000-000000000003"
STAFF = "10000000-0000-0000-0000-000000000004"
VENUE = "20000000-0000-0000-0000-000000000001"
EVENT = "30000000-0000-0000-0000-000000000001"
BOOKING = "40000000-0000-0000-0000-000000000001"
HEADERS = {"X-Dev-User-Id": STAFF, "X-Dev-Role": "Venue Staff"}


def command(args, **kwargs):
    result = subprocess.run(
        args, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, **kwargs
    )
    if result.returncode:
        raise RuntimeError(f"{args[0:3]} exited {result.returncode}: {result.stdout}")
    return result.stdout.strip()


def port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def wait(check, seconds=90):
    end = time.monotonic() + seconds
    error = None
    while time.monotonic() < end:
        try:
            value = check()
            if value:
                return value
        except Exception as caught:
            error = caught
        time.sleep(0.2)
    raise AssertionError(f"timeout: {error}")


class Harness:
    def __init__(self, evidence):
        self.evidence = evidence
        evidence.mkdir(parents=True, exist_ok=True)
        self.identifier = "scrum173-" + uuid4().hex[:12]
        self.containers = []
        self.processes = []
        self.files = []
        self.checks = []
        self.env = {
            key: os.environ[key]
            for key in ("PATH", "HOME", "UV_CACHE_DIR", "SSL_CERT_FILE")
            if key in os.environ
        }
        self.env.update(
            PYTHONUNBUFFERED="1",
            PYTHON_DOTENV_DISABLED="1",
            FLASK_SKIP_DOTENV="1",
            FRONTEND_ORIGIN="http://127.0.0.1:59999",
            INTERNAL_SERVICE_TOKEN=TOKEN,
            CLOSURE_CONFIRMATION_KEY=KEY,
            VENUE_CLOSURE_DEV_MODE="true",
            CALENDAR_DEV_MODE="false",
            NOTIFICATION_DEV_MODE="true",
        )

    def record(self, name, data=None):
        self.checks.append({"check": name, "data": data})
        print("PASS", name, flush=True)
        (self.evidence / "checks.json").write_text(
            json.dumps(self.checks, default=str, indent=2)
        )

    def container(self, suffix, image, inside, env):
        name = self.identifier + "-" + suffix
        self.containers.append(name)
        host_port = port()
        command(
            [
                "docker",
                "run",
                "-d",
                "--name",
                name,
                "-p",
                f"127.0.0.1:{host_port}:{inside}",
                *[item for k, v in env.items() for item in ("-e", f"{k}={v}")],
                image,
            ]
        )
        return int(command(["docker", "port", name, str(inside)]).rsplit(":", 1)[1])

    def setup(self):
        import hashlib

        source_files = []
        for service in (
            "event-service",
            "venue-service",
            "venue-availability-service",
            "venue-booking-service",
            "notification-service",
        ):
            source_files.extend((ROOT / "services" / service / "app").glob("*.py"))
            source_files.extend(
                ROOT / "services" / service / name
                for name in ("pyproject.toml", "uv.lock")
            )
        source_files.extend((ROOT / "database/supabase/migrations").glob("*.sql"))
        source_files.append(Path(__file__))
        metadata = {
            "baseHead": command(["git", "rev-parse", "HEAD"], cwd=ROOT),
            "sourceSha256": {
                str(path.relative_to(ROOT)): hashlib.sha256(
                    path.read_bytes()
                ).hexdigest()
                for path in source_files
            },
            "imageDigests": json.loads(
                command(
                    [
                        "docker",
                        "image",
                        "inspect",
                        "postgres:17",
                        "rabbitmq:4-management",
                    ]
                )
            ),
        }
        # Avoid retaining large image config/environment fields: only content digests are needed.
        metadata["imageDigests"] = [
            {"id": image["Id"], "repoDigests": image["RepoDigests"]}
            for image in metadata["imageDigests"]
        ]
        (self.evidence / "source-and-images.json").write_text(
            json.dumps(metadata, indent=2)
        )
        pg = self.container(
            "postgres",
            "postgres:17",
            5432,
            {"POSTGRES_PASSWORD": "synthetic-only", "POSTGRES_USER": "isolated"},
        )
        rabbit = self.container(
            "rabbit",
            "rabbitmq:4-management",
            5672,
            {
                "RABBITMQ_DEFAULT_USER": "isolated",
                "RABBITMQ_DEFAULT_PASS": "synthetic-only",
            },
        )
        self.rabbit = self.containers[-1]
        self.infra_ports = [pg, rabbit]
        self.admin = f"postgresql://isolated:synthetic-only@127.0.0.1:{pg}/postgres"
        self.env["RABBITMQ_URL"] = (
            f"amqp://isolated:synthetic-only@127.0.0.1:{rabbit}/%2F"
        )

        def ready():
            con = psycopg2.connect(self.admin)
            con.close()
            return True

        wait(ready)
        wait(
            lambda: (
                self.run(
                    "notification-service",
                    "from app.consumer import *; c=connect(os.environ['RABBITMQ_URL']); declare(c.channel()); c.close(); print('ready')",
                )
                == "ready"
            )
        )
        self.dsns = {}
        # Infrastructure fixture: exact baseline DDL for each owner plus only its
        # existing FK prerequisites. Never install another owner's business tables.
        import re

        owners = {
            "notifications": {"User", "Event", "Notification"},
            "availability": {"User", "Event", "Venue", "VenueBooking", "VenueClosure"},
            "events": {"User", "Event"},
            "venues": {"User", "Venue"},
        }
        migrations = ROOT / "database/supabase/migrations"
        baseline = (migrations / "20261011140000_baseline_schema.sql").read_text()
        baseline = re.sub(r"--[^\n]*", "", baseline)
        for database, tables in owners.items():
            con = psycopg2.connect(self.admin)
            con.autocommit = True
            with con.cursor() as cur:
                cur.execute("CREATE DATABASE " + database)
            con.close()
            dsn = self.admin.rsplit("/", 1)[0] + "/" + database
            self.dsns[database] = dsn
            con = psycopg2.connect(dsn)
            try:
                with con, con.cursor() as cur:
                    before = []
                    for statement in baseline.split(";"):
                        target = re.search(r'(?:TABLE(?: IF NOT EXISTS| ONLY)?|ON) "public"\."([^"]+)"', statement)
                        if target and target.group(1) in tables:
                            cur.execute(statement)
                    if database == "availability":
                        for name in (
                            "20261012234245_require_venue_closure_metadata.sql",
                            "20261016000000_booking_closure_rejection.sql",
                            "20261016100000_add_hold_coordinator.sql",
                            "20261016120000_validate_venue_buffer_times.sql",
                        ):
                            cur.execute((migrations / name).read_text())
                    if database == "notifications":
                        # Preserve nullable and duplicate recipient-NULL legacy records.
                        cur.execute('INSERT INTO public."Notification" (dedupe_key) VALUES (%s),(%s)',
                                    ("legacy-before-migration", "legacy-before-migration"))
                        cur.execute('SELECT to_jsonb(n) FROM public."Notification" n ORDER BY notification_id')
                        before = cur.fetchall()
                    if database == "notifications":
                        cur.execute((migrations / "20261017000000_notification_inbox.sql").read_text())
                    elif database == "availability":
                        cur.execute((migrations / "20261017000001_venue_notification_outbox.sql").read_text())
                    if database == "notifications":
                        cur.execute("SELECT to_jsonb(n)-'source_id' FROM public.\"Notification\" n ORDER BY notification_id")
                        assert cur.fetchall() == before
                    expected = tables | ({"NotificationFailure"} if database == "notifications" else
                                         {"VenueNotificationOutbox"} if database == "availability" else set())
                    cur.execute("SELECT tablename FROM pg_tables WHERE schemaname='public'")
                    assert {row[0] for row in cur.fetchall()} == expected
                    cur.execute("""SELECT child.relname, parent.relname
                        FROM pg_constraint c
                        JOIN pg_class child ON child.oid=c.conrelid
                        JOIN pg_class parent ON parent.oid=c.confrelid
                        WHERE c.contype='f' AND child.relnamespace='public'::regnamespace""")
                    foreign_keys = sorted(cur.fetchall())
                    if database == "notifications":
                        assert [parent for child, parent in foreign_keys if child == "Notification"] == ["Event", "User"]
                    elif database == "availability":
                        assert [parent for child, parent in foreign_keys if child == "VenueNotificationOutbox"] == ["VenueBooking", "VenueClosure"]
                    cur.execute("SELECT relname FROM pg_class WHERE relnamespace='public'::regnamespace AND relrowsecurity")
                    rls_tables = sorted(row[0] for row in cur.fetchall())
                    assert set(rls_tables) == expected
                    for user in (A, B, C, STAFF):
                        cur.execute(
                            'INSERT INTO public."User"(user_id,username,role) VALUES (%s,%s,%s)',
                            (
                                user,
                                "Synthetic " + user[-1],
                                "Venue Staff" if user == STAFF else "Event Coordinator",
                            ),
                        )
                    if database in ("availability", "venues"):
                        cur.execute(
                            'INSERT INTO public."Venue"(venue_id,venue_name,operational_status,max_capacity) VALUES (%s,%s,%s,100)',
                            (VENUE, "Synthetic Hall", "Available"),
                        )
                    if database in ("availability", "events", "notifications"):
                        cur.execute(
                            'INSERT INTO public."Event"(event_id,event_name,coordinator_id,status) VALUES (%s,%s,%s,%s)',
                            (EVENT, "Synthetic Conference", A, "Under Review"),
                        )
                    if database == "availability":
                        cur.execute(
                            'INSERT INTO public."VenueBooking"(booking_id,event_id,venue_id,status,requested_start_time,requested_end_time,required_capacity) VALUES (%s,%s,%s,%s,%s,%s,20)',
                            (
                                BOOKING,
                                EVENT,
                                VENUE,
                                "Approved",
                                "2099-01-01T09:00:00+08:00",
                                "2099-01-01T12:00:00+08:00",
                            ),
                        )
            finally:
                con.close()
            if database in ("notifications", "availability"):
                self.record("R3: independent " + database + " owner migration; exact minimal schema and existing FKs retained",
                            {"tables": sorted(expected), "foreignKeys": foreign_keys,
                             "rlsEnabledTables": rls_tables})
        self.urls = {}
        for service, database in [
            ("event-service", "events"),
            ("venue-service", "venues"),
            ("venue-availability-service", "availability"),
            ("notification-service", "notifications"),
            ("venue-booking-service", None),
        ]:
            for dependency, key in [
                ("event-service", "EVENT_SERVICE_URL"),
                ("venue-service", "VENUE_SERVICE_URL"),
                ("venue-availability-service", "VENUE_AVAILABILITY_SERVICE_URL"),
            ]:
                if dependency in self.urls:
                    self.env[key] = self.urls[dependency]
            selected = port()
            self.urls[service] = f"http://127.0.0.1:{selected}"
            self.start(
                service,
                [
                    "flask",
                    "--app",
                    "app",
                    "run",
                    "--host",
                    "127.0.0.1",
                    "--port",
                    str(selected),
                ],
                database,
            )
            wait(lambda: self.http(service, "GET", "/health")[0] == 200)
        self.record(
            "owned setup: four separate databases and five real HTTP processes",
            self.urls,
        )

    def start(self, service, args, database=None):
        env = {
            **self.env,
            "DATABASE_URL": self.dsns[database]
            if database
            else "postgresql://invalid:invalid@127.0.0.1:1/not-owned-by-composite",
        }
        logfile = open(self.evidence / f"{service}-{len(self.processes)}.log", "w")
        self.files.append(logfile)
        proc = subprocess.Popen(
            ["uv", "run", "--no-env-file", *args],
            cwd=ROOT / "services" / service,
            env=env,
            stdout=logfile,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        self.processes.append(proc)
        return proc

    def run(self, service, code, database=None):
        env = {
            **self.env,
            "DATABASE_URL": self.dsns[database]
            if database
            else "postgresql://invalid:invalid@127.0.0.1:1/composite-cannot-use-database",
        }
        output = command(
            ["uv", "run", "--no-env-file", "python", "-c", code],
            cwd=ROOT / "services" / service,
            env=env,
        )
        with open(self.evidence / "subcommands.log", "a") as log:
            log.write(code + "\n" + output + "\n")
        return output

    def http(self, service, method, path, data=None, headers=None):
        req = urllib.request.Request(
            self.urls[service] + path,
            data=json.dumps(data).encode() if data is not None else None,
            method=method,
            headers={"Content-Type": "application/json", **(headers or {})},
        )
        try:
            with urllib.request.urlopen(req, timeout=15) as response:
                return response.status, json.load(response)
        except urllib.error.HTTPError as error:
            return error.code, json.load(error)

    def sql(self, database, sql, params=()):
        con = psycopg2.connect(self.dsns[database])
        try:
            with con, con.cursor() as cur:
                cur.execute(sql, params or None)
                return cur.fetchall() if cur.description else None
        finally:
            con.close()

    def operation(self, job, action, **data):
        return self.http(
            "venue-availability-service",
            "POST",
            f"/internal/notification-outbox/{job['id']}/{action}",
            {"leaseToken": job["leaseToken"], **data},
            {"X-Internal-Token": TOKEN},
        )

    def claim(self):
        status, result = self.http(
            "venue-availability-service",
            "POST",
            "/internal/notification-outbox/claim",
            {},
            {"X-Internal-Token": TOKEN},
        )
        assert status == 200, (status, result)
        return result["jobs"]

    def closure(self, data):
        status, preview = self.http(
            "venue-booking-service", "POST", "/venue-closures/preview", data, HEADERS
        )
        assert status == 200, (status, preview)
        return self.http(
            "venue-booking-service",
            "POST",
            "/venue-closures",
            data
            | {"confirmed": True, "confirmationToken": preview["confirmationToken"]},
            HEADERS,
        )

    def cleanup(self):
        errors = []
        for proc in reversed(self.processes):
            try:
                if proc.poll() is None:
                    os.killpg(proc.pid, signal.SIGTERM)
                    try:
                        proc.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        os.killpg(proc.pid, signal.SIGKILL)
                        proc.wait(timeout=5)
            except ProcessLookupError:
                pass
            except Exception as error:
                errors.append(str(error))
        for file in self.files:
            file.close()
        for name in reversed(self.containers):
            logs = subprocess.run(
                ["docker", "logs", name], capture_output=True, text=True
            )
            (self.evidence / (name + ".log")).write_text(logs.stdout + logs.stderr)
            state = subprocess.run(
                ["docker", "inspect", name], capture_output=True, text=True
            )
            volumes = (
                [
                    mount["Name"]
                    for container in json.loads(state.stdout or "[]")
                    for mount in container.get("Mounts", [])
                    if mount.get("Type") == "volume"
                ]
                if state.returncode == 0
                else []
            )
            removed = subprocess.run(
                ["docker", "rm", "-fv", name], capture_output=True, text=True
            )
            for volume in volumes:
                if (
                    subprocess.run(
                        ["docker", "volume", "inspect", volume],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                    ).returncode
                    == 0
                ):
                    errors.append(f"Owned anonymous volume still exists: {volume}")
            exists = (
                subprocess.run(
                    ["docker", "inspect", name],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                ).returncode
                == 0
            )
            if exists:
                errors.append(f"Owned container still exists: {name}: {removed.stderr}")
        ports = [
            int(url.rsplit(":", 1)[1]) for url in getattr(self, "urls", {}).values()
        ]
        ports.extend(getattr(self, "infra_ports", []))
        for selected in ports:
            with socket.socket() as sock:
                if sock.connect_ex(("127.0.0.1", selected)) == 0:
                    errors.append(f"Owned port still open: {selected}")
        if errors:
            raise AssertionError("; ".join(errors))
        self.record(
            "owned containers/volumes removed; all service AND infrastructure ports closed"
        )


def exercise(h):
    availability = "venue-availability-service"
    inbox = "notification-service"
    data = dict(
        venueId=VENUE,
        startDateTime="2099-01-01T08:00:00+08:00",
        endDateTime="2099-01-02T08:00:00+08:00",
        reason="Maintenance\nOperational safety",
    )
    legacy_ids = [str(uuid4()), str(uuid4())]
    for identifier, recipient in zip(legacy_ids, (A, B)):
        h.sql(
            "notifications",
            'INSERT INTO public."Notification"(notification_id,recipient_id,dedupe_key) VALUES (%s,%s,%s)',
            (identifier, recipient, "legacy-recipient-scoped-key"),
        )
    legacy_before = h.sql(
        "notifications",
        'SELECT * FROM public."Notification" WHERE source_id IS NULL ORDER BY notification_id',
    )
    # Inject actual PostgreSQL outbox failure, not mocked rollback.
    h.sql(
        "availability",
        """CREATE FUNCTION fail_outbox() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'injected isolated failure'; END; $$;
        CREATE TRIGGER fail_outbox BEFORE INSERT ON public."VenueNotificationOutbox" FOR EACH ROW EXECUTE FUNCTION fail_outbox();""",
    )
    status, result = h.closure(data)
    assert status == 503, (status, result)
    assert h.sql(
        "availability",
        'SELECT status FROM public."VenueBooking" WHERE booking_id=%s',
        (BOOKING,),
    ) == [("Approved",)]
    assert h.sql("availability", 'SELECT count(*) FROM public."VenueClosure"') == [(0,)]
    assert h.sql(
        "availability", 'SELECT count(*) FROM public."VenueNotificationOutbox"'
    ) == [(0,)]
    h.record("outbox insertion failure rolls back closure AND rejection AND intent")
    h.sql(
        "availability",
        'DROP TRIGGER fail_outbox ON public."VenueNotificationOutbox"; DROP FUNCTION fail_outbox()',
    )
    status, result = h.closure(data)
    assert status == 201, (status, result)
    assert h.sql(
        "availability",
        'SELECT status FROM public."VenueBooking" WHERE booking_id=%s',
        (BOOKING,),
    ) == [("Rejected",)]
    assert h.sql(
        "availability", 'SELECT count(*) FROM public."VenueNotificationOutbox"'
    ) == [(1,)]
    h.record(
        "real composite closure creates one rejection and one outbox intent", result
    )
    status, result = h.closure(
        data
        | dict(
            startDateTime="2099-02-01T08:00:00+08:00",
            endDateTime="2099-02-02T08:00:00+08:00",
        )
    )
    assert status == 201 and result["rejectedCount"] == 0, (status, result)
    assert h.sql(
        "availability", 'SELECT count(*) FROM public."VenueNotificationOutbox"'
    ) == [(1,)]
    h.record("no-impact closure produces no extra intent")
    with ThreadPoolExecutor(2) as pool:
        claims = list(pool.map(lambda _: h.claim(), range(2)))
    assert sorted(map(len, claims)) == [0, 1], claims
    old = next(items[0] for items in claims if items)
    h.sql(
        "availability",
        """UPDATE public."VenueNotificationOutbox" SET lease_until=now()-interval '1 second' """,
    )
    job = h.claim()[0]
    assert job["leaseToken"] != old["leaseToken"]
    assert h.operation(old, "retry", error="stale")[0] == 409
    assert h.operation(old, "freeze", envelope={})[0] == 409
    assert h.operation(old, "published")[0] == 409
    h.record(
        "concurrent claim and abandoned lease recovery; stale worker fenced on every mutation"
    )
    # A lease that expires while waiting for a row lock must be checked AFTER the lock.
    h.sql(
        "availability",
        """UPDATE public."VenueNotificationOutbox" SET lease_until=clock_timestamp()+interval '0.6 seconds'""",
    )
    blocker = psycopg2.connect(h.dsns["availability"])
    try:
        with blocker.cursor() as cursor:
            cursor.execute(
                'SELECT source_id FROM public."VenueNotificationOutbox" FOR UPDATE'
            )
        with ThreadPoolExecutor(1) as pool:
            pending = pool.submit(h.operation, job, "freeze", envelope={})
            wait(
                lambda: (
                    h.sql(
                        "availability",
                        "SELECT count(*) FROM pg_stat_activity WHERE datname=current_database() AND wait_event_type='Lock' AND query LIKE '%VenueNotificationOutbox%'",
                    )[0][0]
                    >= 1
                ),
                seconds=5,
            )
            wait(
                lambda: h.sql(
                    "availability",
                    'SELECT clock_timestamp()>lease_until FROM public."VenueNotificationOutbox"',
                )[0][0],
                seconds=5,
            )
            blocker.commit()
            status, body = pending.result(timeout=10)
            assert status == 409, (status, body)
    finally:
        blocker.close()
    job = h.claim()[0]
    h.record(
        "lease expiration while waiting on a real row lock fences the resumed stale worker"
    )
    assert h.operation(job, "retry", error="fixture release")[0] == 200
    h.sql(
        "availability", 'UPDATE public."VenueNotificationOutbox" SET available_at=now()'
    )
    h.sql(
        "events",
        'UPDATE public."Event" SET coordinator_id=%s WHERE event_id=%s',
        (B, EVENT),
    )
    h.sql(
        "events",
        'UPDATE public."Event" SET coordinator_id=NULL WHERE event_id=%s',
        (EVENT,),
    )
    h.run(
        "venue-booking-service",
        "from app.dispatcher import *; assert dispatch_once(OutboxAPI(),publish)==1",
    )
    assert h.sql(
        "availability",
        'SELECT envelope,published_at FROM public."VenueNotificationOutbox"',
    ) == [(None, None)]
    assert h.claim() == []  # Backoff is respected rather than immediate busy retry.
    h.sql(
        "events",
        'UPDATE public."Event" SET coordinator_id=%s WHERE event_id=%s',
        (B, EVENT),
    )
    h.sql(
        "availability", 'UPDATE public."VenueNotificationOutbox" SET available_at=now()'
    )
    h.record(
        "absent assignment leaves intent retryable and unfrozen; no fallback recipient or silent drop"
    )
    # Actual worker process death after owner freeze, before any broker publication.
    try:
        h.run(
            "venue-booking-service",
            "from app.dispatcher import *\ndef crash_before_publish(envelope):\n os._exit(17)\ndispatch_once(OutboxAPI(),crash_before_publish)",
        )
    except RuntimeError as error:
        assert "exited 17" in str(error), str(error)
    else:
        raise AssertionError("crash fixture did not terminate the worker")
    crashed = h.sql(
        "availability",
        'SELECT envelope,published_at,lease_until>now() FROM public."VenueNotificationOutbox"',
    )[0]
    assert crashed[0]["recipientId"] == B and crashed[1] is None and crashed[2] is True
    assert h.claim() == []
    h.sql(
        "availability",
        """UPDATE public."VenueNotificationOutbox" SET lease_until=now()-interval '1 second'""",
    )
    h.record(
        "actual dispatcher process death after freeze leaves a recoverable lease and original envelope"
    )
    # Broker outage after freeze: closure remains successful and retry keeps original recipient.
    command(["docker", "stop", h.rabbit])
    h.run(
        "venue-booking-service",
        "from app.dispatcher import *; assert dispatch_once(OutboxAPI(),publish)==1",
    )
    frozen = h.sql(
        "availability",
        'SELECT envelope,attempts,available_at>now(),published_at FROM public."VenueNotificationOutbox"',
    )[0]
    envelope = frozen[0]
    first_delay = h.sql(
        "availability",
        'SELECT extract(epoch FROM available_at-clock_timestamp()) FROM public."VenueNotificationOutbox"',
    )[0][0]
    assert envelope["recipientId"] == B and frozen[2] is True and frozen[3] is None
    assert envelope["details"] == dict(
        data,
        closureId=envelope["details"]["closureId"],
        bookingId=BOOKING,
        eventId=EVENT,
        eventName="Synthetic Conference",
        venueName="Synthetic Hall",
    )
    assert envelope["destination"] == dict(
        kind="event-venue-request", eventId=EVENT, bookingId=BOOKING
    )
    assert (
        envelope["message"]
        == "Synthetic Conference: venue request for Synthetic Hall rejected. Closure 2099-01-01T08:00:00+08:00 to 2099-01-02T08:00:00+08:00. Reason: Maintenance\nOperational safety"
    )
    h.record(
        "broker outage retries without rollback; complete content/destination and current preparation recipient frozen",
        envelope,
    )
    h.sql(
        "events",
        'UPDATE public."Event" SET coordinator_id=%s,event_name=%s WHERE event_id=%s',
        (C, "Changed later", EVENT),
    )
    command(["docker", "start", h.rabbit])
    wait(
        lambda: (
            h.run(
                "notification-service",
                "from app.consumer import *; c=connect(os.environ['RABBITMQ_URL']); declare(c.channel()); c.close(); print('ready')",
                "notifications",
            )
            == "ready"
        )
    )
    h.sql(
        "availability", 'UPDATE public."VenueNotificationOutbox" SET available_at=now()'
    )
    # Publish really succeeds, but its caller observes an unknown outcome.
    assert "REAL_PUBLISH_CONFIRMED" in h.run(
        "venue-booking-service",
        "from app.dispatcher import *\ndef unknown(e):\n publish(e)\n print('REAL_PUBLISH_CONFIRMED')\n raise RuntimeError('lost confirmation after real confirmed publish')\nassert dispatch_once(OutboxAPI(),unknown)==1",
    )
    retry = h.sql(
        "availability",
        'SELECT envelope,attempts,available_at>now(),published_at FROM public."VenueNotificationOutbox"',
    )[0]
    assert (
        retry[0] == envelope and retry[1] > frozen[1] and retry[2] and retry[3] is None
    )
    h.record(
        "confirmed publish followed by unknown caller outcome remains retryable with exact original envelope"
    )
    assert h.claim() == []  # Unknown-publish retry also observes its delay.
    second_delay = h.sql(
        "availability",
        'SELECT extract(epoch FROM available_at-clock_timestamp()) FROM public."VenueNotificationOutbox"',
    )[0][0]
    assert second_delay > first_delay > 0
    # Owned persistence fixture accelerates the retry-count boundary; no wall-clock wait of five minutes.
    h.sql(
        "availability",
        'UPDATE public."VenueNotificationOutbox" SET attempts=999,available_at=now()',
    )
    capped_job = h.claim()[0]
    assert h.operation(capped_job, "retry", error="owned retry-cap probe")[0] == 200
    capped_delay = h.sql(
        "availability",
        'SELECT extract(epoch FROM available_at-clock_timestamp()) FROM public."VenueNotificationOutbox"',
    )[0][0]
    assert 295 < capped_delay <= 300
    h.record(
        "real retry delays increase and remain bounded at 300 seconds",
        {
            "firstDelaySeconds": float(first_delay),
            "secondDelaySeconds": float(second_delay),
            "cappedDelaySeconds": float(capped_delay),
        },
    )

    # Real delivery commits, then connection closes without broker ack.
    h.run(
        "notification-service",
        "from app.consumer import *\nc=connect(os.environ['RABBITMQ_URL']); ch=c.channel(); declare(ch); method,props,body=ch.basic_get(QUEUE,auto_ack=False); assert method\nclass LostAck:\n def basic_ack(self,**kw): raise RuntimeError('lost ack after commit')\ntry: process(os.environ['DATABASE_URL'],LostAck(),method,body)\nexcept RuntimeError: pass\nc.close()",
        "notifications",
    )
    owner = {"X-Dev-User-Id": B, "X-Dev-Role": "Event Coordinator"}
    status, result = h.http(inbox, "GET", "/notifications", headers=owner)
    assert status == 200 and len(result["notifications"]) == 1, (status, result)
    item = result["notifications"][0]
    assert item["payload"] == envelope
    assert (
        h.http(inbox, "PATCH", f"/notifications/{item['id']}", {"read": True}, owner)[0]
        == 200
    )
    h.run(
        "notification-service",
        "from app.consumer import *\nc=connect(os.environ['RABBITMQ_URL']); ch=c.channel(); method,props,body=ch.basic_get(QUEUE,auto_ack=False); assert method and method.redelivered; process(os.environ['DATABASE_URL'],ch,method,body); c.close()",
        "notifications",
    )
    h.record("real inbox commit-before-ack redelivery deduplicated")
    h.sql(
        "availability", 'UPDATE public."VenueNotificationOutbox" SET available_at=now()'
    )
    h.run(
        "venue-booking-service",
        "from app.dispatcher import *; assert dispatch_once(OutboxAPI(),publish)==1",
    )
    h.run(
        "venue-booking-service",
        "from app.dispatcher import *; import json; e=json.loads("
        + repr(json.dumps(envelope))
        + "); publish(e); publish(e)",
    )
    h.run(
        "notification-service",
        "from app.consumer import *\nfrom concurrent.futures import ThreadPoolExecutor\nfrom threading import Barrier\nb=Barrier(2)\ndef consume(_):\n c=connect(os.environ['RABBITMQ_URL']); ch=c.channel(); method,props,body=ch.basic_get(QUEUE,auto_ack=False); assert method; b.wait(timeout=10); process(os.environ['DATABASE_URL'],ch,method,body); c.close()\nwith ThreadPoolExecutor(2) as pool: list(pool.map(consume,range(2)))",
        "notifications",
    )
    assert h.sql(
        "notifications",
        'SELECT count(*) FROM public."Notification" WHERE source_id IS NOT NULL',
    ) == [(1,)]
    h.record(
        "two real broker consumers concurrently persist the same source without duplicate alerts"
    )
    h.start(inbox, ["python", "-m", "app.consumer"], "notifications")
    wait(
        lambda: (
            h.sql(
                "availability",
                'SELECT published_at IS NOT NULL FROM public."VenueNotificationOutbox"',
            )
            == [(True,)]
        )
    )
    wait(
        lambda: (
            h.sql(
                "notifications",
                'SELECT count(*) FROM public."Notification" WHERE source_id IS NOT NULL',
            )
            == [(1,)]
        )
    )
    # Wait for duplicate queue message to be consumed and acknowledged.
    time.sleep(1)
    result = h.http(inbox, "GET", "/notifications", headers=owner)[1]
    assert (
        len(result["notifications"]) == 1
        and result["notifications"][0]["readAt"] is not None
        and result["notifications"][0]["payload"] == envelope
    )
    assert h.http(inbox, "GET", "/notifications/unread-count", headers=owner)[1] == {
        "unreadCount": 0
    }
    stranger = {"X-Dev-User-Id": C, "X-Dev-Role": "Event Coordinator"}
    assert (
        h.http(inbox, "GET", "/notifications", headers=stranger)[1]["notifications"]
        == []
    )
    assert (
        h.http(
            inbox, "PATCH", f"/notifications/{item['id']}", {"read": False}, stranger
        )[0]
        == 404
    )
    assert (
        h.http(inbox, "PATCH", f"/notifications/{item['id']}", {"read": False}, owner)[
            0
        ]
        == 200
    )
    assert (
        h.http(inbox, "GET", "/notifications?unread=true", headers=owner)[1][
            "notifications"
        ][0]["id"]
        == item["id"]
    )
    assert h.http(inbox, "GET", "/notifications/unread-count", headers=owner)[1] == {
        "unreadCount": 1
    }
    h.record(
        "eventual delivery after outage/unknown publish, one alert, preserved read state and ownership/read-unread APIs"
    )
    h.run(
        "venue-booking-service",
        "from app.dispatcher import *\nparams=pika.URLParameters(os.environ['RABBITMQ_URL']); c=pika.BlockingConnection(params); ch=c.channel(); ch.basic_publish(exchange='',routing_key=QUEUE,body=b'malformed'); c.close()",
    )
    wait(
        lambda: (
            h.sql("notifications", 'SELECT count(*) FROM public."NotificationFailure"')
            == [(1,)]
        )
    )
    assert (
        h.sql("notifications", 'SELECT body FROM public."NotificationFailure"')[0][
            0
        ].tobytes()
        == b"malformed"
    )
    # A valid historical envelope retained diagnostically can be replayed repeatedly safely.
    replay_id = str(uuid4())
    h.sql(
        "notifications",
        'INSERT INTO public."NotificationFailure"(failure_id,body,error) VALUES (%s,%s,%s)',
        (replay_id, json.dumps(envelope).encode(), "owned replay fixture"),
    )
    h.run(
        inbox,
        f"from app.diagnostics import *; replay(os.environ['DATABASE_URL'],'{replay_id}'); replay(os.environ['DATABASE_URL'],'{replay_id}'); print(inspect(os.environ['DATABASE_URL']))",
        "notifications",
    )
    assert h.sql(
        "notifications",
        'SELECT count(*) FROM public."Notification" WHERE source_id IS NOT NULL',
    ) == [(1,)]
    h.record(
        "malformed messages durably retained without requeue loop; developer replay idempotent"
    )
    # Healthy steady-state delivery uses the real long-running dispatcher and consumer.
    h.start("venue-booking-service", ["python", "-m", "app.dispatcher"])
    healthy_ids = []
    latencies = []
    for day in (1, 3):
        booking_id = str(uuid4())
        healthy_ids.append(booking_id)
        h.sql(
            "availability",
            'INSERT INTO public."VenueBooking"(booking_id,event_id,venue_id,status,requested_start_time,requested_end_time,required_capacity) VALUES (%s,%s,%s,%s,%s,%s,20)',
            (
                booking_id,
                EVENT,
                VENUE,
                "Approved",
                f"2099-03-{day:02d}T09:00:00+08:00",
                f"2099-03-{day:02d}T12:00:00+08:00",
            ),
        )
        started = time.monotonic()
        status, result = h.closure(
            data
            | dict(
                startDateTime=f"2099-03-{day:02d}T08:00:00+08:00",
                endDateTime=f"2099-03-{day + 1:02d}T08:00:00+08:00",
            )
        )
        assert status == 201, (status, result)
        wait(
            lambda: any(
                item["payload"]["destination"]["bookingId"] == booking_id
                for item in h.http(inbox, "GET", "/notifications", headers=stranger)[1][
                    "notifications"
                ]
            ),
            seconds=30,
        )
        latencies.append(time.monotonic() - started)
    first = h.http(inbox, "GET", "/notifications?limit=1", headers=stranger)[1]
    assert len(first["notifications"]) == 1 and first["nextCursor"]
    second = h.http(
        inbox,
        "GET",
        "/notifications?limit=1&cursor=" + first["nextCursor"],
        headers=stranger,
    )[1]
    assert second["nextCursor"] is None
    assert [
        first["notifications"][0]["payload"]["destination"]["bookingId"],
        second["notifications"][0]["payload"]["destination"]["bookingId"],
    ] == list(reversed(healthy_ids))
    assert h.http(inbox, "GET", "/notifications/unread-count", headers=stranger)[1] == {
        "unreadCount": 2
    }
    h.record(
        "healthy background delivery measured; real newest-first keyset pagination and per-user unread count",
        {"latencySeconds": latencies},
    )
    assert (
        h.sql(
            "notifications",
            'SELECT * FROM public."Notification" WHERE source_id IS NULL ORDER BY notification_id',
        )
        == legacy_before
    )
    h.record(
        "legacy nullable inbox rows and recipient-scoped dedupe keys remain untouched"
    )

    # R1: poison must not starve a later valid message on the actual worker.
    poison = []
    for extra in (float("nan"), float("inf"), float("-inf"), "bad\x00text", "\ud800", {"\udfff": ["nested"]}, {"nul\x00key": "text"}):
        poison.append(json.dumps(envelope | {"id": str(uuid4()), "future": extra}).encode())
    valid = envelope | {"id": str(uuid4()), "recipientId": A, "future": {"safe": [True, None, 1.25, "你好"]}}
    before_failures = h.sql("notifications", 'SELECT count(*) FROM public."NotificationFailure"')[0][0]
    h.run(inbox, "from app.consumer import *\nc=connect(os.environ['RABBITMQ_URL']); ch=c.channel(); declare(ch)\nfor body in " + repr(poison + [json.dumps(valid).encode()]) + ": ch.basic_publish(exchange='',routing_key=QUEUE,body=body,properties=pika.BasicProperties(delivery_mode=2))\nc.close()", "notifications")
    wait(lambda: h.sql("notifications", 'SELECT count(*) FROM public."Notification" WHERE source_id=%s', (valid["id"],)) == [(1,)], seconds=15)
    retained = h.sql("notifications", 'SELECT body,error FROM public."NotificationFailure"')
    assert len(retained) == before_failures + len(poison)
    assert set(poison).issubset({bytes(row[0]) for row in retained})
    assert all("\x00" not in row[1] and not any(0xD800 <= ord(c) <= 0xDFFF for c in row[1]) for row in retained)
    h.record("R1-REAL-01: JSONB poison bytes retained; following valid delivery reaches inbox", {"poisonCount": len(poison), "validSource": valid["id"]})

    # R1: an actual server outage is infrastructure, not permanent poison.
    command(["docker", "stop", h.containers[0]])
    retry_valid = envelope | {"id": str(uuid4()), "recipientId": A}
    h.run(inbox, "from app.consumer import *\nc=connect(os.environ['RABBITMQ_URL']); ch=c.channel(); ch.basic_publish(exchange='',routing_key=QUEUE,body=" + repr(json.dumps(retry_valid).encode()) + "); c.close()", "notifications")
    time.sleep(2)
    command(["docker", "start", h.containers[0]])
    wait(lambda: h.sql("notifications", 'SELECT count(*) FROM public."Notification" WHERE source_id=%s', (retry_valid["id"],)) == [(1,)])
    assert h.sql("notifications", 'SELECT count(*) FROM public."NotificationFailure"') == [(before_failures + len(poison),)]
    h.record("R1-REAL-02: PostgreSQL outage reconnects and retries valid delivery without quarantine")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--evidence", type=Path, required=True)
    args = parser.parse_args()
    h = Harness(args.evidence)
    try:
        h.setup()
        exercise(h)
    finally:
        h.cleanup()


if __name__ == "__main__":
    main()

"""Opt-in cross-service SCRUM-46 fixtures; never run against the shared stack."""

import json
import os
from pathlib import Path
import subprocess
import sys
from uuid import uuid4
import httpx
import psycopg2
from psycopg2.extras import RealDictCursor
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.scrum45_support.system import (
    command,
    wait,
    free_port,
    cleanup_owned_resources,
)


class AttendeeStack:
    """Owned HTTP/SQL/worker handles for one isolated SCRUM-46 scenario.
    All endpoints and database identities come from attendee_stack, never shared configuration.
    """
    def __init__(self, env, urls, db_identity, logs):
        self.env, self.urls, self.db_identity, self.logs = env, urls, db_identity, logs

    def query(self, statement, params=()):
        """Run arrange/assert SQL only after matching the live owned container and binding.
        Return dictionary rows (or [] for nonqueries) and always close the independent connection.
        """
        name, identifier, port = self.db_identity
        current = json.loads(command(["docker", "inspect", identifier]))[0]
        assert current["Id"] == identifier and current["Name"] == "/" + name
        assert current["Config"]["Labels"]["connectsphere.test"] == "scrum46-e2e"
        assert current["NetworkSettings"]["Ports"]["5432/tcp"] == [
            {"HostIp": "127.0.0.1", "HostPort": port}
        ]
        connection = psycopg2.connect(self.env["DATABASE_URL"])
        try:
            with connection, connection.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute(statement, params)
                return cursor.fetchall() if cursor.description else []
        finally:
            connection.close()

    def call(self, service, method, path, **kwargs):
        """Call one fixture-owned service and return its successful JSON body.
        Fail with request context on non-2xx rather than silently accepting a broken action.
        """
        response = httpx.request(
            method, self.urls[service] + path, timeout=10, **kwargs
        )
        assert response.is_success, (method, path, response.status_code, response.text)
        return response.json()

    def dispatch(self, owner):
        """Drain one owner through real bounded dispatcher subprocess attempts.
        Record worker output; stop on its no-work exit, not an arbitrary wait interval.
        """
        env = {**self.env, "OUTBOX_OWNER": owner}
        for _ in range(40):
            result = subprocess.run(
                [
                    str(ROOT / "services/event-workflow-service/.venv/bin/python"),
                    "-m",
                    "app.dispatcher",
                    "--attempt",
                ],
                cwd=ROOT / "services/event-workflow-service",
                env=env,
                capture_output=True,
                text=True,
                timeout=55,
            )
            with (self.logs / f"{owner}-dispatcher.log").open("a") as logfile:
                logfile.write(result.stdout + result.stderr)
            if result.returncode == 3:
                return
            assert result.returncode == 0, result.stdout + result.stderr
        raise AssertionError("Outbox did not drain within bounded attempts")

    def inbox(self, user):
        """Read this synthetic attendee identity's current inbox through the real API.
        Dev headers test existing recipient scoping, not authenticated production identity.
        """
        return self.call(
            "notification",
            "GET",
            "/notifications?limit=100",
            headers={"X-Dev-User-Id": user, "X-Dev-Role": "Attendee"},
        )["notifications"]

    def delivered(self, user, source):
        """Wait at most twenty seconds for this exact source ID in this user's inbox.
        An unrelated older message cannot satisfy delivery for the current action.
        """
        return wait(
            lambda: next((n for n in self.inbox(user) if n["id"] == source), None),
            seconds=20,
        )


@pytest.fixture
def attendee_stack(tmp_path):
    """Yield an isolated stack with seven HTTP services, consumer, dispatcher access, PostgreSQL and RabbitMQ.
    Apply the unmodified migration chain with synthetic SQL roles, disable dotenv,
    and bind owned resources to loopback. Teardown attempts all owned process/container
    cleanup and checks volumes even after a failed assertion; no shared stack is used.
    """
    names, processes, logs, volumes = [], [], [], []
    suffix = uuid4().hex
    dbname = "scrum46-pg-" + suffix
    broker = "scrum46-rabbit-" + suffix
    env = {
        key: os.environ[key] for key in ("HOME", "PATH", "TMPDIR") if key in os.environ
    }
    env.update(
        PYTHON_DOTENV_DISABLED="1",
        UV_NO_ENV_FILE="1",
        INTERNAL_SERVICE_TOKEN="synthetic",
        NOTIFICATION_DEV_MODE="true",
        FLASK_DEBUG="0",
    )
    try:
        command(
            [
                "docker",
                "run",
                "-d",
                "--name",
                dbname,
                "--label",
                "connectsphere.test=scrum46-e2e",
                "-p",
                "127.0.0.1::5432",
                "-e",
                "POSTGRES_USER=isolated",
                "-e",
                "POSTGRES_PASSWORD=synthetic-only",
                "postgres:17.6",
            ]
        )
        names.append(dbname)
        inspected = json.loads(command(["docker", "inspect", dbname]))[0]
        volumes.extend(m["Name"] for m in inspected["Mounts"] if m["Type"] == "volume")
        port = inspected["NetworkSettings"]["Ports"]["5432/tcp"][0]["HostPort"]
        env["DATABASE_URL"] = (
            f"postgresql://isolated:synthetic-only@127.0.0.1:{port}/isolated"
        )
        stack = AttendeeStack(env, {}, (dbname, inspected["Id"], port), tmp_path)
        wait(lambda: stack.query("SELECT 1"))
        connection = psycopg2.connect(env["DATABASE_URL"])
        try:
            connection.autocommit = True
            with connection.cursor() as cursor:
                cursor.execute(
                    "CREATE ROLE anon NOLOGIN; CREATE ROLE authenticated NOLOGIN; CREATE ROLE service_role NOLOGIN BYPASSRLS;"
                )
                for migration in sorted(
                    (ROOT / "database/supabase/migrations").glob("*.sql")
                ):
                    import hashlib

                    payload = migration.read_bytes()
                    cursor.execute(payload.decode())
                    assert (
                        hashlib.sha256(migration.read_bytes()).digest()
                        == hashlib.sha256(payload).digest()
                    )
        finally:
            connection.close()
        command(
            [
                "docker",
                "run",
                "-d",
                "--name",
                broker,
                "--user",
                "999:999",
                "--tmpfs",
                "/var/lib/rabbitmq:uid=999,gid=999,mode=0700",
                "--label",
                "connectsphere.test=scrum46-e2e",
                "-p",
                "127.0.0.1::5672",
                "-e",
                "RABBITMQ_DEFAULT_USER=isolated",
                "-e",
                "RABBITMQ_DEFAULT_PASS=synthetic-only",
                "-e",
                "RABBITMQ_SERVER_ADDITIONAL_ERL_ARGS=+S 2:2",
                "rabbitmq:4-management",
            ]
        )
        names.append(broker)
        wait(
            lambda: command(
                ["docker", "exec", broker, "rabbitmq-diagnostics", "-q", "ping"]
            )
        )
        info = json.loads(command(["docker", "inspect", broker]))[0]
        broker_port = info["NetworkSettings"]["Ports"]["5672/tcp"][0]["HostPort"]
        env["RABBITMQ_URL"] = (
            f"amqp://isolated:synthetic-only@127.0.0.1:{broker_port}/%2F"
        )
        volumes.extend(m["Name"] for m in info["Mounts"] if m["Type"] == "volume")
        for name in (
            "event",
            "registration",
            "venue-availability",
            "venue",
            "user",
            "attendee-registration",
            "notification",
        ):
            stack.urls[name] = f"http://127.0.0.1:{free_port()}"
            env[name.upper().replace("-", "_") + "_SERVICE_URL"] = stack.urls[name]
        for name, url in stack.urls.items():
            logfile = (tmp_path / f"{name}.log").open("w")
            logs.append(logfile)
            process = subprocess.Popen(
                [
                    str(ROOT / f"services/{name}-service/.venv/bin/python"),
                    "-m",
                    "flask",
                    "--app",
                    "app",
                    "run",
                    "--host",
                    "127.0.0.1",
                    "--port",
                    url.rsplit(":", 1)[1],
                ],
                cwd=ROOT / f"services/{name}-service",
                env=env,
                stdout=logfile,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
            processes.append(process)
            wait(lambda: httpx.get(url + "/health", timeout=2).is_success)
        logfile = (tmp_path / "consumer.log").open("w")
        logs.append(logfile)
        processes.append(
            subprocess.Popen(
                [
                    str(ROOT / "services/notification-service/.venv/bin/python"),
                    "-m",
                    "app.consumer",
                ],
                cwd=ROOT / "services/notification-service",
                env=env,
                stdout=logfile,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
        )
        yield stack
    finally:
        diagnostic_failures = []
        try:
            for name in names:
                try:
                    result = subprocess.run(
                        ["docker", "logs", name], capture_output=True, text=True, timeout=15
                    )
                    (tmp_path / (name + ".log")).write_text(result.stdout + result.stderr)
                except Exception as error:
                    diagnostic_failures.append(f"{name} log capture: {type(error).__name__}")
        finally:
            failures = cleanup_owned_resources(processes, logs, names)
        failures.extend(diagnostic_failures)
        existing = command(
            ["docker", "volume", "ls", "--format", "{{.Name}}"]
        ).splitlines()
        if set(volumes).intersection(existing):
            failures.append("Owned anonymous volumes remain")
        assert not failures, "; ".join(failures)
        print(
            "CLEANUP: exact owned process groups, containers and volumes absent",
            flush=True,
        )

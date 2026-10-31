"""Opt-in Equipment Request + disposable PostgreSQL only. No stack runner."""
from contextlib import closing
import json
import os
from pathlib import Path
import socket
import subprocess
from uuid import uuid4

import psycopg2
from psycopg2.extensions import parse_dsn
import pytest
from tests.integration.equipment_request_db_helpers import Database, OwnerAPI, install_schema, wait_for

PG_IMAGE = "postgres@sha256:2d2b8998d31037bf721cfdf764d76ba74171b4fab3431b7f72c27c56ddbdf9e3"


@pytest.fixture(scope="session")
def postgres_environment():
    """Native libpq reads PG* outside Python sockets: remove inherited routing."""
    with pytest.MonkeyPatch.context() as patch:
        for key in list(os.environ):
            if key.startswith("PG") or key in (
                "DATABASE_URL", "NOTIFICATION_DATABASE_URL", "RABBITMQ_URL",
            ):
                patch.delenv(key)
        patch.setenv("PYTHON_DOTENV_DISABLED", "1")
        yield


@pytest.fixture(scope="session")
def postgres(postgres_environment):
    """Fresh UUID container, tmpfs, loopback port; preserve all existing containers."""
    run_id = str(uuid4())
    name = f"scrum48-owner-{run_id}"
    env = {k: os.environ[k] for k in ("PATH","HOME","TMPDIR","LANG","LC_ALL") if k in os.environ}
    env["PYTHON_DOTENV_DISABLED"] = "1"
    report = Path(os.environ.get("SCRUM48_OWNER_EVIDENCE", os.environ["TMPDIR"])) / run_id
    report.mkdir(parents=True, exist_ok=False)
    commands = []
    def cmd(args, check=True):
        result = subprocess.run(["docker",*args],env=env,capture_output=True,text=True,timeout=60)
        commands.append(dict(argv=["docker",*args],exit=result.returncode,stdout=result.stdout,stderr=result.stderr))
        if check:
            assert result.returncode == 0, result.stderr
        return result.stdout.strip()
    def inventory():
        ids = cmd(["ps","-aq"]).splitlines()
        if not ids:
            return {}
        lines = cmd(["inspect","--format",'{{.Id}} {{.Name}} {{.Image}} {{.State.StartedAt}}',*ids]).splitlines()
        return {line.split()[0]:line for line in lines}
    before = inventory()
    cleanup: dict[str, object] = dict(owned_container=name,run_id=run_id)
    primary = None
    try:
        cmd(["image","inspect","--format","{{.Id}}",PG_IMAGE])
        cmd(["run","--pull=never","-d","--name",name,"--label",f"scrum48.owner={run_id}",
             "--tmpfs","/var/lib/postgresql/data","-p","127.0.0.1::5432",
             "-e","POSTGRES_PASSWORD=disposable-only",PG_IMAGE])
        assert cmd(["inspect","--format",'{{index .Config.Labels "scrum48.owner"}}',name]) == run_id
        mapped = cmd(["port",name,"5432"])
        assert mapped.startswith("127.0.0.1:") and len(mapped.splitlines()) == 1
        admin = Database(int(mapped.split(":")[1]),"postgres")
        wait_for(lambda: admin.execute("SELECT 1 AS ready"))
        admin.execute("""CREATE ROLE anon LOGIN PASSWORD 'disposable-only';
        CREATE ROLE authenticated LOGIN PASSWORD 'disposable-only';
        CREATE ROLE service_role LOGIN BYPASSRLS PASSWORD 'disposable-only';
        CREATE ROLE public_probe LOGIN PASSWORD 'disposable-only';""")
        cleanup["postgres_version"] = admin.execute("SELECT version() AS version")[0]["version"]
        yield admin
    except BaseException as error:
        primary = error
        raise
    finally:
        errors = []
        try:
            label = cmd(["inspect","--format",'{{index .Config.Labels "scrum48.owner"}}',name],check=False)
            if label:
                assert label == run_id, "container ownership mismatch"
                cmd(["rm","-fv",name])
            cleanup["owned_container_absent"] = not cmd(["ps","-aq","--filter",f"name=^/{name}$"])
        except Exception as error:
            errors.append(repr(error))
        try:
            after = inventory()
            cleanup["preexisting_count"] = len(before)
            cleanup["preexisting_unchanged"] = all(after.get(k)==v for k,v in before.items())
            (report / "containers-before.json").write_text(json.dumps(before,indent=2))
            (report / "containers-after.json").write_text(json.dumps(after,indent=2))
        except Exception as error:
            errors.append(repr(error))
        cleanup["errors"] = errors
        (report / "commands.json").write_text(json.dumps(commands,indent=2))
        (report / "cleanup.json").write_text(json.dumps(cleanup,indent=2))
        if primary is None:
            assert not errors and cleanup.get("owned_container_absent") and cleanup.get("preexisting_unchanged"), cleanup


@pytest.fixture
def owner(postgres, monkeypatch):
    """Fresh database per case; native libpq restricted to exact owned port/DBs."""
    name = "owner_" + uuid4().hex
    db = Database(postgres.port,name)
    real_connect = psycopg2.connect
    def checked_connect(dsn=None, **kwargs):
        values = {**parse_dsn(dsn or ""),**kwargs}
        assert values.get("host") == "127.0.0.1"
        assert int(values.get("port",0)) == postgres.port
        assert values.get("dbname") in ("postgres",name)
        assert not any(key in values for key in ("hostaddr","service","servicefile"))
        return real_connect(dsn,**kwargs)
    def forbidden(*args, **kwargs):
        pytest.fail("owner integration permits native owned PostgreSQL only")
    monkeypatch.setattr(psycopg2,"connect",checked_connect)
    monkeypatch.setattr(socket.socket,"connect",forbidden)
    monkeypatch.setattr(socket.socket,"connect_ex",forbidden)
    monkeypatch.setenv("PYTHON_DOTENV_DISABLED","1")
    monkeypatch.setenv("DATABASE_URL",db.dsn)
    with closing(psycopg2.connect(postgres.dsn)) as conn:
        conn.autocommit = True
        with conn.cursor() as cur:
            cur.execute(f'CREATE DATABASE "{name}"')
    try:
        db.execute("ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON TABLES TO PUBLIC, anon, authenticated, service_role")
        install_schema(db)
        yield OwnerAPI(db)
    finally:
        with closing(psycopg2.connect(postgres.dsn)) as conn:
            conn.autocommit = True
            with conn.cursor() as cur:
                cur.execute(f'DROP DATABASE "{name}" WITH (FORCE)')
                cur.execute("SELECT datname FROM pg_database WHERE datname=%s",[name])
                assert cur.fetchall() == []


@pytest.fixture
def safety_reset_owner(postgres, monkeypatch):
    """Return a real owner API in a fresh exact-owned DB with all migrations applied."""
    name = "safety_reset_" + uuid4().hex
    db = Database(postgres.port, name)
    real_connect = psycopg2.connect

    def checked_connect(dsn=None, **kwargs):
        """Accept only the fixture's loopback port and admin or generated database."""
        values = {**parse_dsn(dsn or ""), **kwargs}
        assert values.get("host") == "127.0.0.1"
        assert int(values.get("port", 0)) == postgres.port
        assert values.get("dbname") in ("postgres", name)
        assert not any(key in values for key in ("hostaddr", "service", "servicefile"))
        return real_connect(dsn, **kwargs)

    def forbidden(*args, **kwargs):
        """Refuse outbound Python network calls; only guarded native libpq is allowed."""
        pytest.fail("safety reset integration permits native owned PostgreSQL only")

    monkeypatch.setattr(psycopg2, "connect", checked_connect)
    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(socket.socket, "connect_ex", forbidden)
    monkeypatch.setenv("PYTHON_DOTENV_DISABLED", "1")
    monkeypatch.setenv("DATABASE_URL", db.dsn)
    with closing(psycopg2.connect(postgres.dsn)) as conn:
        conn.autocommit = True
        with conn.cursor() as cur:
            cur.execute(f'CREATE DATABASE "{name}"')
    try:
        migrations = Path(__file__).resolve().parents[4] / "database/supabase/migrations"
        with closing(psycopg2.connect(db.dsn)) as conn:
            conn.autocommit = True
            with conn.cursor() as cur:
                for migration in sorted(migrations.glob("*.sql")):
                    cur.execute(migration.read_text())
        yield OwnerAPI(db)
    finally:
        with closing(psycopg2.connect(postgres.dsn)) as conn:
            conn.autocommit = True
            with conn.cursor() as cur:
                cur.execute(f'DROP DATABASE "{name}" WITH (FORCE)')
                cur.execute("SELECT datname FROM pg_database WHERE datname=%s", [name])
                assert cur.fetchall() == []

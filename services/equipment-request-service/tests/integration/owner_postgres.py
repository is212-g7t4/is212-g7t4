"""Owner-only PostgreSQL fixtures: no other production service is imported.
Baseline Event/User/Equipment tables are inert FK scaffolding, not running services.
"""
from contextlib import closing
from pathlib import Path
import re
import time
from uuid import uuid4
import psycopg2
from psycopg2.extras import RealDictCursor
from app import create_app

ROOT = Path(__file__).resolve().parents[4]
TOKEN = "disposable-internal-token"


def uid():
    return str(uuid4())


def wait_for(check, seconds=30):
    end = time.monotonic() + seconds
    last = None
    while time.monotonic() < end:
        try:
            result = check()
            if result:
                return result
        except Exception as error:
            last = error
        time.sleep(.05)
    raise AssertionError(f"owned resource not ready: {last}")


class Database:
    def __init__(self, port, name):
        self.port, self.name = int(port), name
        self.dsn = f"host=127.0.0.1 port={self.port} dbname={name} user=postgres password=disposable-only connect_timeout=3"

    def execute(self, statement, params=None):
        """Every observation uses a new connection/transaction, never a stateful SQL double."""
        with closing(psycopg2.connect(self.dsn)) as connection:
            with connection, connection.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute(statement, params)
                return [dict(row) for row in cursor.fetchall()] if cursor.description else []

    def snapshot(self):
        return {table: self.execute(f'SELECT * FROM public."{table}" ORDER BY 1')
                for table in ("EquipmentRequest", "EquipmentNotificationOutbox")}

    def fail_outbox_insert(self, number):
        """PostgreSQL trigger fails the first/later insert; nontransactional sequence proves it ran."""
        self.execute(f"""CREATE SEQUENCE fault_calls;
        CREATE FUNCTION fail_outbox() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
          IF nextval('fault_calls') = {int(number)} THEN
             RAISE EXCEPTION 'SCRUM48 injected outbox failure' USING ERRCODE='P0001';
          END IF;
          RETURN NEW;
        END $$;
        CREATE TRIGGER fail_outbox BEFORE INSERT ON public."EquipmentNotificationOutbox"
          FOR EACH ROW EXECUTE FUNCTION fail_outbox();""")


def install_schema(db):
    """Apply owner FK scaffolding and the exact owner outbox migration only.
    Other domains are deliberately absent: this is not a full migration-history test.
    """
    tables = {"Equipment", "EquipmentRequest", "Event", "User"}
    raw = (ROOT / "database/supabase/migrations/20261011140000_baseline_schema.sql").read_text()
    raw = re.sub(r"--[^\n]*", "", raw)
    for statement in raw.split(";"):
        statement = statement.strip()
        match = re.search(r'(?:CREATE TABLE IF NOT EXISTS|ALTER TABLE(?: ONLY)?) "public"\."(\w+)"', statement)
        if match and match.group(1) in tables:
            db.execute(statement)
    for name in ("20261028000000_equipment_notification_outbox.sql",):
        db.execute((ROOT / "database/supabase/migrations" / name).read_text())


class OwnerAPI:
    def __init__(self, db):
        self.db = db
        self.event, self.coordinator, self.reviewer, self.other = (uid() for _ in range(4))
        self.tss = [self.reviewer, self.other]
        self.equipment = [uid(), uid()]
        for user in [self.coordinator, *self.tss]:
            db.execute('INSERT INTO public."User" (user_id) VALUES (%s)', [user])
        db.execute('INSERT INTO public."Event" (event_id,event_name,coordinator_id) VALUES (%s,%s,%s)', [self.event, "Community Fair", self.coordinator])
        for identifier, name in zip(self.equipment, ("Microphone", "Projector")):
            db.execute('INSERT INTO public."Equipment" (equipment_id,description,total_quantity) VALUES (%s,%s,20)', [identifier, name])
        self.context = dict(eventId=self.event, eventName="Community Fair", equipmentNames=dict(zip(self.equipment, ("Microphone", "Projector"))), recipientIds=self.tss, coordinatorId=self.coordinator)
        self.app = create_app()
        self.app.config.update(TESTING=False, DATABASE_URL=db.dsn, INTERNAL_SERVICE_TOKEN=TOKEN)
        self.client = self.app.test_client()

    def identity(self, role="Technical Support", user=None, trusted=True):
        headers = {"X-Dev-User-Id": user or self.reviewer, "X-Dev-Role": role}
        if trusted:
            headers["X-Internal-Token"] = TOKEN
        return headers

    def submit(self, recipients=None):
        context = dict(self.context)
        if recipients is not None:
            context["recipientIds"] = recipients
        return self.client.post(f"/events/{self.event}/equipment-requests", headers=self.identity("Event Coordinator", self.coordinator), json={"items": [dict(equipmentId=eid, quantityRequested=qty) for eid, qty in zip(self.equipment, (5,2))], "notificationContext": context})

    def seed_requests(self, count=3):
        rows = []
        for index in range(count):
            row = self.db.execute('INSERT INTO public."EquipmentRequest" (event_id,equipment_id,quantity_requested,status,requested_by) VALUES (%s,%s,%s,%s,%s) RETURNING equipment_request_id', [self.event, self.equipment[index % 2], (5,2)[index % 2], "Pending", self.coordinator])[0]
            rows.append(str(row["equipment_request_id"]))
        return rows

    def review(self, identifier=None, status="Approved", context=None, headers=None):
        path = f"/equipment-requests/{identifier}" if identifier else f"/events/{self.event}/equipment-requests"
        return self.client.patch(path, headers=headers or self.identity(), json=dict(status=status, rejectionReason="Private workflow reason", notificationContext=context or self.context))

    def outbox(self):
        return self.db.execute('SELECT * FROM public."EquipmentNotificationOutbox" ORDER BY source_id')

    def operation(self, job, action, **data):
        return self.client.post(f"/internal/notification-outbox/{job['id']}/{action}", headers={"X-Internal-Token": TOKEN}, json=dict(leaseToken=job["leaseToken"], **data))

    def claim(self):
        response = self.client.post("/internal/notification-outbox/claim", headers={"X-Internal-Token": TOKEN}, json={})
        assert response.status_code == 200, response.json
        return response.json["jobs"]

    def expire(self, identifier):
        self.db.execute("""UPDATE public."EquipmentNotificationOutbox" SET lease_until=clock_timestamp()-interval '1 second', available_at=clock_timestamp()-interval '1 second' WHERE source_id=%s""", [identifier])

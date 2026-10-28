-- SCRUM-48. Owner: Equipment Request Service. No historical backfill/triggers.
BEGIN;
CREATE TABLE public."EquipmentNotificationOutbox" (
 source_id uuid PRIMARY KEY,
 type varchar(50) NOT NULL CHECK (type IN ('equipment.request-submission', 'equipment.request-decision')),
 source jsonb NOT NULL,
 envelope jsonb NOT NULL,
 created_at timestamptz NOT NULL DEFAULT now(),
 published_at timestamptz,
 attempts integer NOT NULL DEFAULT 0,
 available_at timestamptz NOT NULL DEFAULT now(),
 lease_token uuid, lease_until timestamptz, last_error text
);
CREATE INDEX equipment_outbox_pending ON public."EquipmentNotificationOutbox" (available_at)
 WHERE published_at IS NULL;
ALTER TABLE public."EquipmentNotificationOutbox" ENABLE ROW LEVEL SECURITY;
-- Only the service's privileged postgres connection uses this table; no client policies.
-- RLS does not protect TRUNCATE; remove inherited default table grants explicitly.
-- service_role is unused by the owner backend and needs no access to this outbox.
REVOKE ALL PRIVILEGES ON TABLE public."EquipmentNotificationOutbox"
 FROM PUBLIC, anon, authenticated, service_role;
COMMIT;

-- SCRUM-46. Registration owns action intent; no cross-owner writes or backfill.
CREATE TABLE public."RegistrationNotificationOutbox" (
 source_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
 type varchar(50) NOT NULL CHECK (type IN ('registration.confirmed','registration.withdrawn')),
 source jsonb NOT NULL, envelope jsonb,
 created_at timestamptz NOT NULL DEFAULT now(), published_at timestamptz,
 attempts integer NOT NULL DEFAULT 0, available_at timestamptz NOT NULL DEFAULT now(),
 lease_token uuid, lease_until timestamptz, last_error text
);
CREATE INDEX registration_outbox_pending ON public."RegistrationNotificationOutbox" (available_at) WHERE published_at IS NULL;
ALTER TABLE public."RegistrationNotificationOutbox" ENABLE ROW LEVEL SECURITY;
-- A privileged owner connection is required; inherited API grants bypassing RLS
-- or permitting TRUNCATE must not expose this internal delivery queue.
REVOKE ALL PRIVILEGES ON TABLE public."RegistrationNotificationOutbox"
 FROM PUBLIC, anon, authenticated, service_role;
DO $$
DECLARE existing_expression text;
BEGIN
 SELECT pg_get_expr(conbin,conrelid) INTO STRICT existing_expression FROM pg_constraint
 WHERE conrelid='public."EventNotificationOutbox"'::regclass AND conname='EventNotificationOutbox_type_check';
 ALTER TABLE public."EventNotificationOutbox" DROP CONSTRAINT "EventNotificationOutbox_type_check";
 EXECUTE 'ALTER TABLE public."EventNotificationOutbox" ADD CONSTRAINT "EventNotificationOutbox_type_check" CHECK (('
 || existing_expression || ') OR type IN (''attendee.cancelled-fanout'',''attendee.updated-fanout'',''attendee.event-cancelled'',''attendee.event-updated''))';
END $$;

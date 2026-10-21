-- Owner: Event Service. Written on the same transaction as each new rejection.
CREATE TABLE public."EventNotificationOutbox" (
 source_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
 type varchar(50) NOT NULL CHECK (type = 'event.rejection'),
 source jsonb NOT NULL, envelope jsonb,
 created_at timestamptz NOT NULL DEFAULT now(), published_at timestamptz,
 attempts integer NOT NULL DEFAULT 0, available_at timestamptz NOT NULL DEFAULT now(),
 lease_token uuid, lease_until timestamptz, last_error text
);
CREATE INDEX event_outbox_pending ON public."EventNotificationOutbox" (available_at) WHERE published_at IS NULL;
ALTER TABLE public."EventNotificationOutbox" ENABLE ROW LEVEL SECURITY;

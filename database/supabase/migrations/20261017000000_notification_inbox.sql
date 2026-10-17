-- Owner: Notification. Requires existing Notification and its User/Event FKs only.
-- SCRUM-173: reuse Notification, preserve nullable legacy records.
-- A separate source identity avoids changing the meaning of legacy recipient-scoped keys.
ALTER TABLE public."Notification" ADD COLUMN source_id uuid;
CREATE UNIQUE INDEX notification_source_unique ON public."Notification" (source_id) WHERE source_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS notification_inbox_order ON public."Notification" (recipient_id,created_at DESC,notification_id DESC);
CREATE TABLE public."NotificationFailure" (
 failure_id uuid PRIMARY KEY DEFAULT gen_random_uuid(), body bytea NOT NULL,
 error text NOT NULL, created_at timestamptz NOT NULL DEFAULT now(), replayed_at timestamptz
);
ALTER TABLE public."NotificationFailure" ENABLE ROW LEVEL SECURITY;

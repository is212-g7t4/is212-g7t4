-- Organiser change-request audit fields and the one-pending-request rule.
ALTER TABLE public."EventChangeReq"
    ADD COLUMN IF NOT EXISTS requested_by uuid,
    ADD COLUMN IF NOT EXISTS reason text;

ALTER TABLE public."EventChangeReq"
    DROP CONSTRAINT IF EXISTS event_changereq_requested_by_fkey;

ALTER TABLE public."EventChangeReq"
    ADD CONSTRAINT event_changereq_requested_by_fkey
    FOREIGN KEY (requested_by) REFERENCES public."User"(user_id);

CREATE UNIQUE INDEX IF NOT EXISTS event_changereq_one_pending_per_event
    ON public."EventChangeReq" (event_id)
    WHERE status = 'Pending Review';

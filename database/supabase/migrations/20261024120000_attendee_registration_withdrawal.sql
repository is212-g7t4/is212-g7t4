-- Optional organiser withdrawal cutoff and auditable attendee withdrawals.
ALTER TABLE public."Event"
    ADD COLUMN IF NOT EXISTS withdrawal_deadline timestamp with time zone;

ALTER TABLE public."Registration"
    ADD COLUMN IF NOT EXISTS withdrawn_at timestamp with time zone;

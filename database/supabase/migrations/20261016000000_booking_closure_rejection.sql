-- SCRUM-171: additive, nullable historical rejection explanation. No backfill.
BEGIN;
ALTER TABLE public."VenueBooking"
    ADD COLUMN rejection_closure_id uuid REFERENCES public."VenueClosure" (closure_id),
    ADD COLUMN rejection_closure_start timestamptz,
    ADD COLUMN rejection_closure_end timestamptz,
    ADD COLUMN rejection_closure_reason text,
    ADD COLUMN rejected_at timestamptz,
    ADD CONSTRAINT venue_booking_closure_rejection_consistent CHECK (
        (rejection_closure_id IS NULL AND rejection_closure_start IS NULL
         AND rejection_closure_end IS NULL AND rejection_closure_reason IS NULL AND rejected_at IS NULL)
        OR
        (rejection_closure_id IS NOT NULL AND rejection_closure_start IS NOT NULL
         AND rejection_closure_end IS NOT NULL AND rejection_closure_reason IS NOT NULL
         AND rejected_at IS NOT NULL AND status IS NOT NULL AND status = 'Rejected'
         AND rejection_closure_end > rejection_closure_start
         AND length(btrim(rejection_closure_reason)) > 0)
    );
CREATE INDEX venue_booking_rejection_closure_idx
    ON public."VenueBooking" (rejection_closure_id) WHERE rejection_closure_id IS NOT NULL;
COMMIT;

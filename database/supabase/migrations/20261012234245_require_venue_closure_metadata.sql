-- SCRUM-170: every closure must identify its venue, creator and creation time.
-- The baseline already requires closure_id, start_date_time, end_date_time,
-- and reason. Keep existing names, foreign keys and service validation rules.
--
-- Preflight on the target database before deployment:
-- SELECT count(*) FROM public."VenueClosure"
-- WHERE venue_id IS NULL OR created_by IS NULL OR created_at IS NULL;
-- If nonzero, resolve records with their owner first. Do not fabricate a
-- creator/time, delete records, or silently backfill historical information.
-- ALTER fails if any existing value is NULL; this transaction prevents a
-- partially applied change. No database reset or seed execution is required.
BEGIN;
ALTER TABLE public."VenueClosure"
    ALTER COLUMN venue_id SET NOT NULL,
    ALTER COLUMN created_by SET NOT NULL,
    ALTER COLUMN created_at SET NOT NULL;
COMMIT;

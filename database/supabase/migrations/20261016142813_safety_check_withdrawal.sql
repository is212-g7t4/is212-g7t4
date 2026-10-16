-- SCRUM-153: a high-impact change to a 'Confirmed' event withdraws its safety
-- approval. The approved round keeps its decision fields (who approved, when,
-- with what remarks) and gains who withdrew it, when and why, so AC3's "it
-- stays visible in the event's safety history" holds.
--
-- All three are nullable with no backfill: existing rows are untouched, and
-- every round that was never withdrawn simply reads NULL.
ALTER TABLE ONLY public."SafetyCheck"
    ADD COLUMN IF NOT EXISTS "withdrawn_at" timestamp with time zone,
    ADD COLUMN IF NOT EXISTS "withdrawn_by" "uuid",
    ADD COLUMN IF NOT EXISTS "withdrawal_reason" "text";

ALTER TABLE ONLY public."SafetyCheck"
    ADD CONSTRAINT "SafetyCheck_withdrawn_by_fkey" FOREIGN KEY ("withdrawn_by") REFERENCES public."User"("user_id");

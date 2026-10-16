-- The Event Coordinator a hold is placed for, who receives the 3-day expiry
-- reminder. Nullable: existing holds and holds placed without a coordinator
-- simply produce no reminder.
ALTER TABLE ONLY public."VenueBooking"
    ADD COLUMN IF NOT EXISTS "held_for" uuid;

ALTER TABLE ONLY public."VenueBooking"
    ADD CONSTRAINT "VenueBooking_held_for_fkey" FOREIGN KEY ("held_for") REFERENCES public."User"("user_id");


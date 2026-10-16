ALTER TABLE public."Venue"
    ADD CONSTRAINT venue_setup_time_nonnegative
        CHECK (setup_time_minutes >= 0),
    ADD CONSTRAINT venue_turnaround_time_nonnegative
        CHECK (turnaround_time_minutes >= 0);

-- Timed venue holds live alongside bookings in Venue Availability so both
-- write paths can enforce the same overlap rules.
create table if not exists public."VenueHold" (
    hold_id uuid primary key default gen_random_uuid(),
    venue_id uuid not null references public."Venue" (venue_id),
    created_at timestamp not null default (now() at time zone 'Asia/Singapore'),
    expires_at timestamp not null,
    held_by uuid references public."User" (user_id),
    constraint venue_hold_expiry_after_creation check (expires_at > created_at)
);

create index if not exists venue_hold_venue_expiry_idx
    on public."VenueHold" (venue_id, created_at, expires_at);
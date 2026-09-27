-- Venue Availability owns both the booking records and conflict-checking
-- (merged design — see AGENTS.md/docs/microservices-catalog.md). No separate
-- Booking Conflict table/service.
create extension if not exists pgcrypto;

create table if not exists public."VenueBooking" (
    booking_id uuid primary key default gen_random_uuid(),
    event_id uuid not null references public."Event" (event_id),
    venue_id uuid not null references public."Venue" (venue_id),
    requested_start_time timestamp not null,
    requested_end_time timestamp not null,
    status varchar(20) not null default 'Pending Review',
    requested_by uuid references public."User" (user_id),
    reviewed_by uuid references public."User" (user_id),
    constraint venue_booking_end_after_start check (requested_end_time > requested_start_time)
);

create index if not exists venue_booking_venue_time_idx
    on public."VenueBooking" (venue_id, requested_start_time, requested_end_time);

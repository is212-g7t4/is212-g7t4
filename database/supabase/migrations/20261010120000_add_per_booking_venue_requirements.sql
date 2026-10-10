-- Each venue arrangement carries its own suitability inputs. Existing rows
-- retain the old behaviour by inheriting the event-level values once.
alter table public."VenueBooking"
    add column if not exists required_capacity integer,
    add column if not exists venue_requirements text;

update public."VenueBooking" booking
set required_capacity = coalesce(booking.required_capacity, event.expected_attendance, 1),
    venue_requirements = coalesce(booking.venue_requirements, event.venue_requirements, '')
from public."Event" event
where event.event_id = booking.event_id
  and (booking.required_capacity is null or booking.venue_requirements is null);

-- Legacy rows can predate enforced event links. Keep the migration deployable
-- while assigning the smallest valid conservative capacity to those rows.
update public."VenueBooking"
set required_capacity = coalesce(required_capacity, 1),
    venue_requirements = coalesce(venue_requirements, '')
where required_capacity is null or venue_requirements is null;

alter table public."VenueBooking"
    alter column required_capacity set not null,
    alter column venue_requirements set default '',
    alter column venue_requirements set not null;

alter table public."VenueBooking"
    drop constraint if exists venue_booking_required_capacity_positive;

alter table public."VenueBooking"
    add constraint venue_booking_required_capacity_positive
    check (required_capacity between 1 and 2147483647);

create index if not exists venue_booking_event_idx
    on public."VenueBooking" (event_id, requested_start_time, booking_id);

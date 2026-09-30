-- Adds a real FK from Event to Venue, so a booked venue can be referenced by
-- id instead of matching on the free-text venue_requirements column.
alter table public."Event"
    add column if not exists venue_id uuid references public."Venue" (venue_id);

create index if not exists event_venue_id_idx on public."Event" (venue_id);

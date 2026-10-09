-- Tables were renamed directly on the shared Supabase project (PascalCase,
-- no "_service" suffix) outside of a tracked migration. This migration
-- captures that rename so migration history matches reality, and so a
-- fresh/local database ends up with the same table names the app code now
-- queries. Schema (columns, types, FKs) is unchanged — names only.
--
-- Quoted identifiers are required from here on in application code, since
-- unquoted names fold to lowercase in Postgres (e.g. `FROM Event` would
-- look for a table literally named "event", not "Event").

alter table if exists public.event_service rename to "Event";
alter table if exists public.user_service rename to "User";
alter table if exists public.registration_service rename to "Registration";
alter table if exists public.equipment_service rename to "Equipment";
alter table if exists public.equipment_request rename to "EquipmentRequest";
alter table if exists public.event_changereq rename to "EventChangeReq";
alter table if exists public.venue_service rename to "Venue";
alter table if exists public.booking_service rename to "VenueBooking";

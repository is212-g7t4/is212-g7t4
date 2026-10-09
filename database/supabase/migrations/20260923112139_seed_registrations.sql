-- Seed sample attendee registrations against "Design Sprint" (Approved,
-- expected_attendance = 20, coordinator Marcus Lim) so registration-service
-- and the event-detail "Registrations" section have something to show
-- locally. Attendees aren't assumed to be platform users, so attendee_id is
-- left null and the free-text attendee_name/email/organization columns are
-- used instead, matching what registration_service already provides for.
--
-- Fixed UUIDs make this idempotent (ON CONFLICT ... DO UPDATE) and safe to
-- re-run. 4 Confirmed + 1 Withdrawn, so "remaining spots" (capacity minus
-- confirmed count) has a real number to compute: 20 - 4 = 16.

insert into public.registration_service
    (registration_id, event_id, attendee_id, registration_date, status,
     attendee_name, attendee_email, attendee_organization)
values
    ('9f725c7a-ac3d-4d4a-937a-84db7906be71', '25c9fe40-c44d-4d79-8d5d-de66d40c1678', null,
     '2026-09-13 09:15:00', 'Confirmed', 'Lena Ho', 'lena.ho@example.com', 'Acme Studio'),
    ('1eec36d7-3c51-4981-8f80-ae62f7f99b7f', '25c9fe40-c44d-4d79-8d5d-de66d40c1678', null,
     '2026-09-13 11:40:00', 'Confirmed', 'Ben Lau', 'ben.lau@example.com', ''),
    ('41b56a8d-98c6-4490-8c7a-c50298ab3344', '25c9fe40-c44d-4d79-8d5d-de66d40c1678', null,
     '2026-09-14 08:05:00', 'Confirmed', 'Farah Idris', 'farah.idris@example.com', 'Northwind Design'),
    ('f813958f-beb3-4c6d-9bfb-7108fc1486ec', '25c9fe40-c44d-4d79-8d5d-de66d40c1678', null,
     '2026-09-14 15:50:00', 'Confirmed', 'Jon Tan', 'jon.tan@example.com', 'Acme Studio'),
    ('c8caaa8b-6a3d-48d8-8b90-2459d3249cfd', '25c9fe40-c44d-4d79-8d5d-de66d40c1678', null,
     '2026-09-15 10:00:00', 'Withdrawn', 'Mei Lin', 'mei.lin@example.com', '')
on conflict (registration_id) do update set
    event_id = excluded.event_id,
    attendee_id = excluded.attendee_id,
    registration_date = excluded.registration_date,
    status = excluded.status,
    attendee_name = excluded.attendee_name,
    attendee_email = excluded.attendee_email,
    attendee_organization = excluded.attendee_organization;

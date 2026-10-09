-- Seed a second Event Organiser (Daniel Koh) with one Approved event and a
-- couple of registrations, so the organiser "My events" / registration view
-- can be tested for isolation: Michael Lee and Daniel Koh must each see only
-- the events they created.
--
-- Fixed UUIDs make this idempotent (ON CONFLICT ... DO UPDATE) and safe to
-- re-run. Uses the PascalCase table names from
-- 20260923115843_rename_tables_to_pascalcase.sql.

insert into public."User"
    (user_id, username, email, role, organization, contact_details, manager_id)
values
    ('b2f6c1d4-8a37-4e59-9c0d-5e1a7f3b2c68', 'Daniel Koh', 'danielkoh@connect.com', 'Event Organiser', 'External', '+65 8222 3344', null)
on conflict (user_id) do update set
    username = excluded.username,
    email = excluded.email,
    role = excluded.role,
    organization = excluded.organization,
    contact_details = excluded.contact_details,
    manager_id = excluded.manager_id;

insert into public."Event"
    (event_id, event_name, description, expected_attendance, preferred_start_date,
     preferred_end_date, status, organiser_id, coordinator_id, submission_date,
     venue_requirements, accessibility_needs, equipment_requirements, registration_needs)
values
    (
        'e41d7a90-6b2c-4f83-a1d5-93c0b8e27f14', 'Startup Pitch Night',
        jsonb_build_object(
            '_connectsphere', 'event-submission-v1',
            'description', 'An evening of five-minute pitches from early-stage startups.',
            'purpose', 'Startup networking',
            'decision', jsonb_build_object(
                'status', 'Approved',
                'coordinatorId', '7110f1a8-e707-4b76-9fb0-57808310da98',
                'decidedAt', '2026-09-25T03:00:00+00:00',
                'reason', null
            ),
            'decisionHistory', jsonb_build_array(jsonb_build_object(
                'status', 'Approved',
                'coordinatorId', '7110f1a8-e707-4b76-9fb0-57808310da98',
                'decidedAt', '2026-09-25T03:00:00+00:00',
                'reason', null
            ))
        )::text,
        50, '2026-10-28 18:00:00', '2026-10-28 21:00:00', 'Approved',
        'b2f6c1d4-8a37-4e59-9c0d-5e1a7f3b2c68', '7110f1a8-e707-4b76-9fb0-57808310da98',
        '2026-09-22 09:30:00', 'Auditorium', '', 'Projector, microphones', ''
    )
on conflict (event_id) do update set
    event_name = excluded.event_name,
    description = excluded.description,
    expected_attendance = excluded.expected_attendance,
    preferred_start_date = excluded.preferred_start_date,
    preferred_end_date = excluded.preferred_end_date,
    status = excluded.status,
    organiser_id = excluded.organiser_id,
    coordinator_id = excluded.coordinator_id,
    submission_date = excluded.submission_date,
    venue_requirements = excluded.venue_requirements,
    accessibility_needs = excluded.accessibility_needs,
    equipment_requirements = excluded.equipment_requirements,
    registration_needs = excluded.registration_needs;

insert into public."Registration"
    (registration_id, event_id, attendee_id, registration_date, status,
     attendee_name, attendee_email, attendee_organization)
values
    ('0a8e5c32-47d1-4b96-8f2a-6d3c91e5b7a0', 'e41d7a90-6b2c-4f83-a1d5-93c0b8e27f14', null,
     '2026-09-26 10:20:00', 'Confirmed', 'Nora Teo', 'nora.teo@example.com', 'Seedling Labs'),
    ('d7c3b941-2e58-4a60-b1f7-8c4a05e92d36', 'e41d7a90-6b2c-4f83-a1d5-93c0b8e27f14', null,
     '2026-09-27 14:05:00', 'Withdrawn', 'Ravi Menon', 'ravi.menon@example.com', '')
on conflict (registration_id) do update set
    event_id = excluded.event_id,
    attendee_id = excluded.attendee_id,
    registration_date = excluded.registration_date,
    status = excluded.status,
    attendee_name = excluded.attendee_name,
    attendee_email = excluded.attendee_email,
    attendee_organization = excluded.attendee_organization;

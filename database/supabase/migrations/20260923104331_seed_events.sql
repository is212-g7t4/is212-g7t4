-- Seed a handful of events across statuses and coordinators, so "My events"
-- and "Submitted event requests" have something to show locally.
--
-- description is stored as a JSON blob matching event-service's
-- "_connectsphere: event-submission-v1" envelope (see
-- services/event-service/app/models.py unpack_decision/serialize) so the
-- frontend can decode description/purpose/decision the same way it does
-- for events created through the real submission flow.
--
-- Fixed UUIDs make this idempotent (ON CONFLICT ... DO UPDATE) and safe to
-- re-run. organiser_id is Michael Lee (Event Organiser); coordinator_id
-- points at Marcus Lim / Priya Nair (both report to Alice Tan) or is left
-- null for one event, to exercise the manager assignment flow.

insert into public.event_service
    (event_id, event_name, description, expected_attendance, preferred_start_date,
     preferred_end_date, status, organiser_id, coordinator_id, submission_date,
     venue_requirements, accessibility_needs, equipment_requirements, registration_needs)
values
    (
        '3c06f811-53fb-4779-a4c5-507e0bb681ee', 'Community Workshop',
        jsonb_build_object(
            '_connectsphere', 'event-submission-v1',
            'description', 'A hands-on workshop for local community members.',
            'purpose', 'Community engagement'
        )::text,
        60, '2026-10-05 09:00:00', '2026-10-05 17:00:00', 'Submitted',
        '3d89d4d2-3502-4bd9-ade8-c9887f2bee45', '7912075d-46f5-405b-9af3-05502f42f173',
        '2026-09-15 10:00:00', 'Innovation Lab', 'Wheelchair accessible entrance required',
        'Projector, whiteboard', 'Online registration required'
    ),
    (
        '5a86c456-0d4f-45fc-b071-70426fe3bba4', 'Tech Conference 2026',
        jsonb_build_object(
            '_connectsphere', 'event-submission-v1',
            'description', 'Annual technology conference for the region.',
            'purpose', 'Industry knowledge sharing'
        )::text,
        280, '2026-11-12 09:00:00', '2026-11-13 18:00:00', 'Submitted',
        '3d89d4d2-3502-4bd9-ade8-c9887f2bee45', '7110f1a8-e707-4b76-9fb0-57808310da98',
        '2026-09-18 14:30:00', 'Auditorium', '', 'Stage AV setup, livestream equipment',
        'Ticketed registration'
    ),
    (
        '25c9fe40-c44d-4d79-8d5d-de66d40c1678', 'Design Sprint',
        jsonb_build_object(
            '_connectsphere', 'event-submission-v1',
            'description', 'A two-day design sprint for the product team.',
            'purpose', 'Product ideation',
            'decision', jsonb_build_object(
                'status', 'Approved',
                'coordinatorId', '7912075d-46f5-405b-9af3-05502f42f173',
                'decidedAt', '2026-09-20T03:00:00+00:00',
                'reason', null
            ),
            'decisionHistory', jsonb_build_array(jsonb_build_object(
                'status', 'Approved',
                'coordinatorId', '7912075d-46f5-405b-9af3-05502f42f173',
                'decidedAt', '2026-09-20T03:00:00+00:00',
                'reason', null
            ))
        )::text,
        20, '2026-10-20 09:00:00', '2026-10-21 17:00:00', 'Approved',
        '3d89d4d2-3502-4bd9-ade8-c9887f2bee45', '7912075d-46f5-405b-9af3-05502f42f173',
        '2026-09-12 08:45:00', 'Innovation Lab', '', 'Whiteboards, sticky notes', ''
    ),
    (
        '7d969563-49c5-469a-977b-5eb0bd84bfcf', 'Charity Gala',
        jsonb_build_object(
            '_connectsphere', 'event-submission-v1',
            'description', 'A fundraising gala dinner.',
            'purpose', 'Fundraising',
            'decision', jsonb_build_object(
                'status', 'Rejected',
                'coordinatorId', '7110f1a8-e707-4b76-9fb0-57808310da98',
                'decidedAt', '2026-09-21T06:15:00+00:00',
                'reason', 'Venue unavailable on the requested date.'
            ),
            'decisionHistory', jsonb_build_array(jsonb_build_object(
                'status', 'Rejected',
                'coordinatorId', '7110f1a8-e707-4b76-9fb0-57808310da98',
                'decidedAt', '2026-09-21T06:15:00+00:00',
                'reason', 'Venue unavailable on the requested date.'
            ))
        )::text,
        150, '2026-12-05 18:00:00', '2026-12-05 23:00:00', 'Rejected',
        '3d89d4d2-3502-4bd9-ade8-c9887f2bee45', '7110f1a8-e707-4b76-9fb0-57808310da98',
        '2026-09-14 11:20:00', 'Grand Ballroom', 'Step-free access to the ballroom',
        'Stage, sound system, lighting', 'RSVP required'
    ),
    (
        '705f7c5c-0ffe-451e-8812-905a5f111a13', 'Networking Mixer',
        jsonb_build_object(
            '_connectsphere', 'event-submission-v1',
            'description', 'An informal networking evening for members.',
            'purpose', 'Networking'
        )::text,
        40, '2026-11-02 18:00:00', '2026-11-02 21:00:00', 'Submitted',
        '3d89d4d2-3502-4bd9-ade8-c9887f2bee45', null,
        '2026-09-19 16:00:00', 'Rooftop Terrace', '', 'PA system', ''
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

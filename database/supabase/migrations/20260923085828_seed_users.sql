-- Seed one user per role, plus Alice Tan's Event Coordinator team.
--
-- Fixed UUIDs make this idempotent (ON CONFLICT ... DO UPDATE) and safe to
-- re-run. The Event Coordinator ids (Alice/Marcus/Priya) and the Event
-- Organiser id (Michael Lee) match real users that already existed in the
-- shared project before this migration was written (Michael Lee's
-- organization/contact_details are his real pre-existing values, carried
-- forward here so this UPSERT only normalizes his role casing rather than
-- overwriting his data) — so existing references and fixtures keep
-- resolving to the same people.
--
-- role values use the frontend's display casing ('Event Coordinator', not
-- 'EventCoordinator') to reconcile the casing mismatch between layers.

insert into public.user_service
    (user_id, username, email, role, organization, contact_details, manager_id)
values
    ('e7334aa9-eb3a-4c45-84b5-280501b6c109', 'Alice Tan', 'alice.tan@connectsphere.example', 'Event Coordinator', 'ConnectSphere', '+65 8111 1111', null),
    ('7912075d-46f5-405b-9af3-05502f42f173', 'Marcus Lim', 'marcus.lim@connectsphere.example', 'Event Coordinator', 'ConnectSphere', '+65 8234 5678', 'e7334aa9-eb3a-4c45-84b5-280501b6c109'),
    ('7110f1a8-e707-4b76-9fb0-57808310da98', 'Priya Nair', 'priya.nair@connectsphere.example', 'Event Coordinator', 'ConnectSphere', '+65 8345 6789', 'e7334aa9-eb3a-4c45-84b5-280501b6c109'),
    ('3d89d4d2-3502-4bd9-ade8-c9887f2bee45', 'Michael Lee', 'michaellee@connect.com', 'Event Organiser', 'External', '+65 8123 4567', null),
    ('d9e4002b-db91-4939-b87e-50f9cceb5e0a', 'Siti Aminah', 'siti.aminah@connectsphere.example', 'Venue Staff', 'ConnectSphere', '+65 8567 8901', null),
    ('ad3d6da3-7220-4f80-9157-2ee4abc0455c', 'Wei Chen', 'wei.chen@connectsphere.example', 'Technical Support', 'ConnectSphere', '+65 8678 9012', null)
on conflict (user_id) do update set
    username = excluded.username,
    email = excluded.email,
    role = excluded.role,
    organization = excluded.organization,
    contact_details = excluded.contact_details,
    manager_id = excluded.manager_id;

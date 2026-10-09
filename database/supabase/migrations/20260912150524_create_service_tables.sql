-- One table per Postgres-backed atomic service, in the public schema.

create table event_service (
    event_id uuid primary key default gen_random_uuid(),
    event_name varchar(255),
    description text,
    expected_attendance integer,
    preferred_start_date timestamp,
    preferred_end_date timestamp,
    status varchar(50),
    organiser_id uuid,
    coordinator_id uuid,
    submission_date timestamp,
    venue_requirements text,
    accessibility_needs text,
    equipment_requirements text,
    registration_needs text
);

create table event_changereq (
    change_id uuid primary key default gen_random_uuid(),
    event_id uuid,
    requested_changes jsonb,
    status varchar(50),
    request_date timestamp,
    rejection_reason text,
    review_date timestamp,
    reviewed_by uuid
);

create table equipment_service (
    equipment_id uuid primary key default gen_random_uuid(),
    equipment_type varchar(100),
    description text,
    total_quantity integer,
    location varchar(255),
    operational_status varchar(50)
);

create table user_service (
    user_id uuid primary key default gen_random_uuid(),
    username varchar(255),
    email varchar(255),
    role varchar(50),
    organization varchar(255),
    contact_details text
);

create table booking_service (
    booking_id uuid primary key default gen_random_uuid(),
    event_id uuid,
    venue_id uuid,
    requested_start_time timestamp,
    requested_end_time timestamp,
    venue_requirements text,
    status varchar(50),
    requested_by uuid,
    reviewed_by uuid,
    rejection_reason text
);

create table venue_service (
    venue_id uuid primary key default gen_random_uuid(),
    venue_name varchar(255),
    location varchar(255),
    max_capacity integer,
    facilities jsonb,
    accessibility text,
    supported_layouts jsonb,
    operational_status varchar(50)
);

create table registration_service (
    registration_id uuid primary key default gen_random_uuid(),
    event_id uuid,
    attendee_id uuid,
    registration_date timestamp,
    status varchar(50),
    attendee_name varchar(255),
    attendee_email varchar(255),
    attendee_organization varchar(255)
);

create table equipment_request (
    equipment_request_id uuid primary key default gen_random_uuid(),
    event_id uuid,
    equipment_id uuid,
    quantity_requested integer,
    technical_requirements text,
    status varchar(50),
    reviewed_by uuid
);

-- Foreign key constraints, added now that all 8 tables exist.

alter table event_service
    add constraint event_service_organiser_id_fkey foreign key (organiser_id) references user_service (user_id),
    add constraint event_service_coordinator_id_fkey foreign key (coordinator_id) references user_service (user_id);

alter table event_changereq
    add constraint event_changereq_event_id_fkey foreign key (event_id) references event_service (event_id),
    add constraint event_changereq_reviewed_by_fkey foreign key (reviewed_by) references user_service (user_id);

alter table booking_service
    add constraint booking_service_event_id_fkey foreign key (event_id) references event_service (event_id),
    add constraint booking_service_venue_id_fkey foreign key (venue_id) references venue_service (venue_id),
    add constraint booking_service_requested_by_fkey foreign key (requested_by) references user_service (user_id),
    add constraint booking_service_reviewed_by_fkey foreign key (reviewed_by) references user_service (user_id);

alter table registration_service
    add constraint registration_service_event_id_fkey foreign key (event_id) references event_service (event_id),
    add constraint registration_service_attendee_id_fkey foreign key (attendee_id) references user_service (user_id);

alter table equipment_request
    add constraint equipment_request_event_id_fkey foreign key (event_id) references event_service (event_id),
    add constraint equipment_request_equipment_id_fkey foreign key (equipment_id) references equipment_service (equipment_id),
    add constraint equipment_request_reviewed_by_fkey foreign key (reviewed_by) references user_service (user_id);

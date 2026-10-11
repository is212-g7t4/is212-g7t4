-- ConnectSphere database schema, exactly as described in docs/db-structure.md.
--
-- The single migration for this project: it replaces every earlier migration
-- file. Constraints are only those the doc lists (PKs, FKs, UNIQUE rules,
-- NOT NULL / DEFAULT where the doc says so, positive required_capacity and
-- the Notification index); every other rule lives in the service code.
-- Some constraint names are legacy (e.g. booking_service_pkey) because tables
-- were renamed to PascalCase after creation; the names do not affect behaviour.
-- Mock data is in ../seed.sql, not here.
--
-- Not created here because Supabase manages them: the rls_auto_enable event
-- trigger and the default grants to anon / authenticated / service_role.

-- Tables

CREATE TABLE IF NOT EXISTS "public"."Equipment" (
    "equipment_id" "uuid" DEFAULT "gen_random_uuid"() NOT NULL,
    "equipment_type" character varying(100),
    "description" "text",
    "total_quantity" integer,
    "location" character varying(255),
    "operational_status" character varying(50)
);

CREATE TABLE IF NOT EXISTS "public"."EquipmentRequest" (
    "equipment_request_id" "uuid" DEFAULT "gen_random_uuid"() NOT NULL,
    "event_id" "uuid",
    "equipment_id" "uuid",
    "quantity_requested" integer,
    "technical_requirements" "text",
    "status" character varying(50),
    "reviewed_by" "uuid",
    "quantity_reserved" integer DEFAULT 0 NOT NULL,
    "requested_by" "uuid",
    "requested_at" timestamp with time zone,
    "reviewed_at" timestamp with time zone,
    "rejection_reason" "text"
);

CREATE TABLE IF NOT EXISTS "public"."Event" (
    "event_id" "uuid" DEFAULT "gen_random_uuid"() NOT NULL,
    "event_name" character varying(255),
    "description" "text",
    "expected_attendance" integer,
    "preferred_start_date" timestamp with time zone,
    "preferred_end_date" timestamp with time zone,
    "status" character varying(50),
    "organiser_id" "uuid",
    "coordinator_id" "uuid",
    "submission_date" timestamp with time zone,
    "venue_requirements" "text",
    "accessibility_needs" "text",
    "equipment_requirements" "text",
    "registration_needs" "text",
    "purpose" "text",
    "registration_enabled" boolean DEFAULT false NOT NULL,
    "rejection_reason" "text",
    "assigned_by" "uuid",
    "assigned_at" timestamp with time zone,
    "previous_coordinator_id" "uuid"
);

CREATE TABLE IF NOT EXISTS "public"."EventChangeReq" (
    "change_id" "uuid" DEFAULT "gen_random_uuid"() NOT NULL,
    "event_id" "uuid",
    "requested_changes" "jsonb",
    "status" character varying(50),
    "request_date" timestamp with time zone,
    "rejection_reason" "text",
    "review_date" timestamp with time zone,
    "reviewed_by" "uuid"
);

CREATE TABLE IF NOT EXISTS "public"."Notification" (
    "notification_id" "uuid" DEFAULT "gen_random_uuid"() NOT NULL,
    "recipient_id" "uuid",
    "type" character varying(50),
    "event_id" "uuid",
    "payload" "jsonb",
    "dedupe_key" character varying(255),
    "created_at" timestamp with time zone,
    "read_at" timestamp with time zone
);

CREATE TABLE IF NOT EXISTS "public"."Registration" (
    "registration_id" "uuid" DEFAULT "gen_random_uuid"() NOT NULL,
    "event_id" "uuid",
    "attendee_id" "uuid",
    "registration_date" timestamp with time zone,
    "status" character varying(50)
);

CREATE TABLE IF NOT EXISTS "public"."SafetyCheck" (
    "safety_check_id" "uuid" DEFAULT "gen_random_uuid"() NOT NULL,
    "event_id" "uuid",
    "round_number" integer NOT NULL,
    "submitted_by" "uuid",
    "submitted_at" timestamp with time zone,
    "equipment_placement_notes" "text",
    "crowd_movement_notes" "text",
    "status" character varying(50),
    "decided_by" "uuid",
    "decided_at" timestamp with time zone,
    "remarks" "text"
);

CREATE TABLE IF NOT EXISTS "public"."SafetyCheckFlag" (
    "flag_id" "uuid" DEFAULT "gen_random_uuid"() NOT NULL,
    "safety_check_id" "uuid",
    "area" character varying(50),
    "booking_id" "uuid",
    "equip_request_id" "uuid",
    "change_required" "text"
);

CREATE TABLE IF NOT EXISTS "public"."User" (
    "user_id" "uuid" DEFAULT "gen_random_uuid"() NOT NULL,
    "username" character varying(255),
    "email" character varying(255),
    "role" character varying(50),
    "organization" character varying(255),
    "contact_details" "text"
);

CREATE TABLE IF NOT EXISTS "public"."Venue" (
    "venue_id" "uuid" DEFAULT "gen_random_uuid"() NOT NULL,
    "venue_name" character varying(255),
    "location" character varying(255),
    "max_capacity" integer,
    "facilities" "jsonb",
    "accessibility" "text",
    "supported_layouts" "jsonb",
    "operational_status" character varying(50),
    "operating_info" "text",
    "setup_time_minutes" integer DEFAULT 0 NOT NULL,
    "turnaround_time_minutes" integer DEFAULT 0 NOT NULL,
    "emergency_access_details" "text",
    "known_restrictions" "text",
    "safety_info_updated_by" "uuid",
    "safety_info_updated_at" timestamp with time zone
);

CREATE TABLE IF NOT EXISTS "public"."VenueBooking" (
    "booking_id" "uuid" DEFAULT "gen_random_uuid"() NOT NULL,
    "event_id" "uuid",
    "venue_id" "uuid",
    "requested_start_time" timestamp with time zone NOT NULL,
    "requested_end_time" timestamp with time zone NOT NULL,
    "venue_requirements" "text",
    "status" character varying(50),
    "requested_by" "uuid",
    "reviewed_by" "uuid",
    "rejection_reason" "text",
    "hold_expires_at" timestamp with time zone,
    "required_capacity" integer NOT NULL,
    "requested_at" timestamp with time zone,
    "reviewed_at" timestamp with time zone,
    "held_by" "uuid",
    "held_at" timestamp with time zone,
    "reminder_sent_at" timestamp with time zone,
    "conflict_reason" character varying(50),
    "closure_id" "uuid",
    CONSTRAINT "venue_booking_required_capacity_positive" CHECK ((("required_capacity" >= 1) AND ("required_capacity" <= 2147483647)))
);

CREATE TABLE IF NOT EXISTS "public"."VenueClosure" (
    "closure_id" "uuid" DEFAULT "gen_random_uuid"() NOT NULL,
    "venue_id" "uuid",
    "start_date_time" timestamp with time zone NOT NULL,
    "end_date_time" timestamp with time zone NOT NULL,
    "reason" "text" NOT NULL,
    "created_by" "uuid",
    "created_at" timestamp with time zone
);

-- Primary keys and unique rules

ALTER TABLE ONLY "public"."Notification"
    ADD CONSTRAINT "Notification_pkey" PRIMARY KEY ("notification_id");

ALTER TABLE ONLY "public"."SafetyCheckFlag"
    ADD CONSTRAINT "SafetyCheckFlag_pkey" PRIMARY KEY ("flag_id");

ALTER TABLE ONLY "public"."SafetyCheck"
    ADD CONSTRAINT "SafetyCheck_pkey" PRIMARY KEY ("safety_check_id");

ALTER TABLE ONLY "public"."VenueClosure"
    ADD CONSTRAINT "VenueClosure_pkey" PRIMARY KEY ("closure_id");

ALTER TABLE ONLY "public"."VenueBooking"
    ADD CONSTRAINT "booking_service_pkey" PRIMARY KEY ("booking_id");

ALTER TABLE ONLY "public"."EquipmentRequest"
    ADD CONSTRAINT "equipment_request_pkey" PRIMARY KEY ("equipment_request_id");

ALTER TABLE ONLY "public"."Equipment"
    ADD CONSTRAINT "equipment_service_pkey" PRIMARY KEY ("equipment_id");

ALTER TABLE ONLY "public"."EventChangeReq"
    ADD CONSTRAINT "event_changereq_pkey" PRIMARY KEY ("change_id");

ALTER TABLE ONLY "public"."Event"
    ADD CONSTRAINT "event_service_pkey" PRIMARY KEY ("event_id");

ALTER TABLE ONLY "public"."Notification"
    ADD CONSTRAINT "notification_recipient_dedupe_key" UNIQUE ("recipient_id", "dedupe_key");

ALTER TABLE ONLY "public"."Registration"
    ADD CONSTRAINT "registration_event_attendee_key" UNIQUE ("event_id", "attendee_id");

ALTER TABLE ONLY "public"."Registration"
    ADD CONSTRAINT "registration_service_pkey" PRIMARY KEY ("registration_id");

ALTER TABLE ONLY "public"."SafetyCheck"
    ADD CONSTRAINT "safety_check_event_round_key" UNIQUE ("event_id", "round_number");

ALTER TABLE ONLY "public"."User"
    ADD CONSTRAINT "user_email_key" UNIQUE ("email");

ALTER TABLE ONLY "public"."User"
    ADD CONSTRAINT "user_service_pkey" PRIMARY KEY ("user_id");

ALTER TABLE ONLY "public"."Venue"
    ADD CONSTRAINT "venue_service_pkey" PRIMARY KEY ("venue_id");

-- Indexes

CREATE INDEX "notification_recipient_created_idx" ON "public"."Notification" USING "btree" ("recipient_id", "created_at");

-- Foreign keys

ALTER TABLE ONLY "public"."EquipmentRequest"
    ADD CONSTRAINT "EquipmentRequest_requested_by_fkey" FOREIGN KEY ("requested_by") REFERENCES "public"."User"("user_id");

ALTER TABLE ONLY "public"."Event"
    ADD CONSTRAINT "Event_assigned_by_fkey" FOREIGN KEY ("assigned_by") REFERENCES "public"."User"("user_id");

ALTER TABLE ONLY "public"."Event"
    ADD CONSTRAINT "Event_previous_coordinator_id_fkey" FOREIGN KEY ("previous_coordinator_id") REFERENCES "public"."User"("user_id");

ALTER TABLE ONLY "public"."Notification"
    ADD CONSTRAINT "Notification_event_id_fkey" FOREIGN KEY ("event_id") REFERENCES "public"."Event"("event_id");

ALTER TABLE ONLY "public"."Notification"
    ADD CONSTRAINT "Notification_recipient_id_fkey" FOREIGN KEY ("recipient_id") REFERENCES "public"."User"("user_id");

ALTER TABLE ONLY "public"."SafetyCheckFlag"
    ADD CONSTRAINT "SafetyCheckFlag_booking_id_fkey" FOREIGN KEY ("booking_id") REFERENCES "public"."VenueBooking"("booking_id");

ALTER TABLE ONLY "public"."SafetyCheckFlag"
    ADD CONSTRAINT "SafetyCheckFlag_equip_request_id_fkey" FOREIGN KEY ("equip_request_id") REFERENCES "public"."EquipmentRequest"("equipment_request_id");

ALTER TABLE ONLY "public"."SafetyCheckFlag"
    ADD CONSTRAINT "SafetyCheckFlag_safety_check_id_fkey" FOREIGN KEY ("safety_check_id") REFERENCES "public"."SafetyCheck"("safety_check_id");

ALTER TABLE ONLY "public"."SafetyCheck"
    ADD CONSTRAINT "SafetyCheck_decided_by_fkey" FOREIGN KEY ("decided_by") REFERENCES "public"."User"("user_id");

ALTER TABLE ONLY "public"."SafetyCheck"
    ADD CONSTRAINT "SafetyCheck_event_id_fkey" FOREIGN KEY ("event_id") REFERENCES "public"."Event"("event_id");

ALTER TABLE ONLY "public"."SafetyCheck"
    ADD CONSTRAINT "SafetyCheck_submitted_by_fkey" FOREIGN KEY ("submitted_by") REFERENCES "public"."User"("user_id");

ALTER TABLE ONLY "public"."VenueBooking"
    ADD CONSTRAINT "VenueBooking_closure_id_fkey" FOREIGN KEY ("closure_id") REFERENCES "public"."VenueClosure"("closure_id");

ALTER TABLE ONLY "public"."VenueBooking"
    ADD CONSTRAINT "VenueBooking_held_by_fkey" FOREIGN KEY ("held_by") REFERENCES "public"."User"("user_id");

ALTER TABLE ONLY "public"."VenueClosure"
    ADD CONSTRAINT "VenueClosure_created_by_fkey" FOREIGN KEY ("created_by") REFERENCES "public"."User"("user_id");

ALTER TABLE ONLY "public"."VenueClosure"
    ADD CONSTRAINT "VenueClosure_venue_id_fkey" FOREIGN KEY ("venue_id") REFERENCES "public"."Venue"("venue_id");

ALTER TABLE ONLY "public"."Venue"
    ADD CONSTRAINT "Venue_safety_info_updated_by_fkey" FOREIGN KEY ("safety_info_updated_by") REFERENCES "public"."User"("user_id");

ALTER TABLE ONLY "public"."VenueBooking"
    ADD CONSTRAINT "booking_service_event_id_fkey" FOREIGN KEY ("event_id") REFERENCES "public"."Event"("event_id");

ALTER TABLE ONLY "public"."VenueBooking"
    ADD CONSTRAINT "booking_service_requested_by_fkey" FOREIGN KEY ("requested_by") REFERENCES "public"."User"("user_id");

ALTER TABLE ONLY "public"."VenueBooking"
    ADD CONSTRAINT "booking_service_reviewed_by_fkey" FOREIGN KEY ("reviewed_by") REFERENCES "public"."User"("user_id");

ALTER TABLE ONLY "public"."VenueBooking"
    ADD CONSTRAINT "booking_service_venue_id_fkey" FOREIGN KEY ("venue_id") REFERENCES "public"."Venue"("venue_id");

ALTER TABLE ONLY "public"."EquipmentRequest"
    ADD CONSTRAINT "equipment_request_equipment_id_fkey" FOREIGN KEY ("equipment_id") REFERENCES "public"."Equipment"("equipment_id");

ALTER TABLE ONLY "public"."EquipmentRequest"
    ADD CONSTRAINT "equipment_request_event_id_fkey" FOREIGN KEY ("event_id") REFERENCES "public"."Event"("event_id");

ALTER TABLE ONLY "public"."EquipmentRequest"
    ADD CONSTRAINT "equipment_request_reviewed_by_fkey" FOREIGN KEY ("reviewed_by") REFERENCES "public"."User"("user_id");

ALTER TABLE ONLY "public"."EventChangeReq"
    ADD CONSTRAINT "event_changereq_event_id_fkey" FOREIGN KEY ("event_id") REFERENCES "public"."Event"("event_id");

ALTER TABLE ONLY "public"."EventChangeReq"
    ADD CONSTRAINT "event_changereq_reviewed_by_fkey" FOREIGN KEY ("reviewed_by") REFERENCES "public"."User"("user_id");

ALTER TABLE ONLY "public"."Event"
    ADD CONSTRAINT "event_service_coordinator_id_fkey" FOREIGN KEY ("coordinator_id") REFERENCES "public"."User"("user_id");

ALTER TABLE ONLY "public"."Event"
    ADD CONSTRAINT "event_service_organiser_id_fkey" FOREIGN KEY ("organiser_id") REFERENCES "public"."User"("user_id");

ALTER TABLE ONLY "public"."Registration"
    ADD CONSTRAINT "registration_service_attendee_id_fkey" FOREIGN KEY ("attendee_id") REFERENCES "public"."User"("user_id");

ALTER TABLE ONLY "public"."Registration"
    ADD CONSTRAINT "registration_service_event_id_fkey" FOREIGN KEY ("event_id") REFERENCES "public"."Event"("event_id");

-- Row level security (no policies: services connect with a privileged role)

ALTER TABLE "public"."Equipment" ENABLE ROW LEVEL SECURITY;
ALTER TABLE "public"."EquipmentRequest" ENABLE ROW LEVEL SECURITY;
ALTER TABLE "public"."Event" ENABLE ROW LEVEL SECURITY;
ALTER TABLE "public"."EventChangeReq" ENABLE ROW LEVEL SECURITY;
ALTER TABLE "public"."Notification" ENABLE ROW LEVEL SECURITY;
ALTER TABLE "public"."Registration" ENABLE ROW LEVEL SECURITY;
ALTER TABLE "public"."SafetyCheck" ENABLE ROW LEVEL SECURITY;
ALTER TABLE "public"."SafetyCheckFlag" ENABLE ROW LEVEL SECURITY;
ALTER TABLE "public"."User" ENABLE ROW LEVEL SECURITY;
ALTER TABLE "public"."Venue" ENABLE ROW LEVEL SECURITY;
ALTER TABLE "public"."VenueBooking" ENABLE ROW LEVEL SECURITY;
ALTER TABLE "public"."VenueClosure" ENABLE ROW LEVEL SECURITY;

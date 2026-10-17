-- Owner: Venue Availability. Requires existing VenueClosure and VenueBooking only.
CREATE TABLE public."VenueNotificationOutbox" (
 source_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
 type varchar(50) NOT NULL DEFAULT 'venue.closure-rejection',
 closure_id uuid NOT NULL REFERENCES public."VenueClosure"(closure_id),
 booking_id uuid NOT NULL REFERENCES public."VenueBooking"(booking_id),
 source jsonb NOT NULL, envelope jsonb,
 created_at timestamptz NOT NULL DEFAULT now(), published_at timestamptz,
 attempts integer NOT NULL DEFAULT 0, available_at timestamptz NOT NULL DEFAULT now(),
 lease_token uuid, lease_until timestamptz, last_error text,
 UNIQUE(type,closure_id,booking_id)
);
CREATE INDEX venue_outbox_pending ON public."VenueNotificationOutbox" (available_at) WHERE published_at IS NULL;
ALTER TABLE public."VenueNotificationOutbox" ENABLE ROW LEVEL SECURITY;

-- SCRUM-47: reuse the booking owner's durable outbox for submission and decision alerts.
BEGIN;
-- Existing closure rows and their deduplication constraint remain unchanged.
ALTER TABLE public."VenueNotificationOutbox" ALTER COLUMN closure_id DROP NOT NULL;
ALTER TABLE public."VenueNotificationOutbox" ADD CONSTRAINT venue_outbox_source_kind
 CHECK ((type = 'venue.closure-rejection' AND closure_id IS NOT NULL)
     OR (type IN ('venue.booking-submission-fanout', 'venue.booking-submission', 'venue.booking-decision')
         AND closure_id IS NULL));
CREATE UNIQUE INDEX venue_outbox_submission_once
 ON public."VenueNotificationOutbox" (booking_id)
 WHERE type = 'venue.booking-submission-fanout';
CREATE UNIQUE INDEX venue_outbox_staff_delivery_once
 ON public."VenueNotificationOutbox" (booking_id, (source->>'recipientId'))
 WHERE type = 'venue.booking-submission';
CREATE UNIQUE INDEX venue_outbox_decision_once
 ON public."VenueNotificationOutbox" (booking_id)
 WHERE type = 'venue.booking-decision';
COMMIT;

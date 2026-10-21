-- SCRUM-45 AC1: preserve rejection work and allow newly recorded approval intent.
ALTER TABLE public."EventNotificationOutbox"
    DROP CONSTRAINT "EventNotificationOutbox_type_check";
ALTER TABLE public."EventNotificationOutbox"
    ADD CONSTRAINT "EventNotificationOutbox_type_check"
    CHECK (type IN ('event.rejection', 'event.approval'));

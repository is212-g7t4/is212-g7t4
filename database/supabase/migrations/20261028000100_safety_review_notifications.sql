-- SCRUM-168: extend the existing Event-owned outbox, without backfill or new tables.
-- Requires EventNotificationOutbox and its named type constraint; preserve all prior types.
DO $$
DECLARE existing_expression text;
BEGIN
 SELECT pg_get_expr(conbin, conrelid) INTO STRICT existing_expression
 FROM pg_constraint
 WHERE conrelid = 'public."EventNotificationOutbox"'::regclass
   AND conname = 'EventNotificationOutbox_type_check';
 ALTER TABLE public."EventNotificationOutbox" DROP CONSTRAINT "EventNotificationOutbox_type_check";
 EXECUTE 'ALTER TABLE public."EventNotificationOutbox" ADD CONSTRAINT "EventNotificationOutbox_type_check" CHECK (('
         || existing_expression || ') OR type IN (''safety.review-fanout'', ''safety.review-submitted'', ''safety.review-decision''))';
END $$;

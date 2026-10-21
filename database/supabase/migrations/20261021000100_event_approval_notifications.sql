-- SCRUM-45 AC1: extend the installed constraint, preserving independently
-- introduced notification types and existing rejection-only installations.
DO $$
DECLARE existing_expression text;
BEGIN
 SELECT pg_get_expr(conbin, conrelid) INTO STRICT existing_expression
 FROM pg_constraint
 WHERE conrelid = 'public."EventNotificationOutbox"'::regclass
   AND conname = 'EventNotificationOutbox_type_check';
 ALTER TABLE public."EventNotificationOutbox" DROP CONSTRAINT "EventNotificationOutbox_type_check";
 EXECUTE 'ALTER TABLE public."EventNotificationOutbox" ADD CONSTRAINT "EventNotificationOutbox_type_check" CHECK (('
         || existing_expression || ') OR type = ''event.approval'')';
END $$;

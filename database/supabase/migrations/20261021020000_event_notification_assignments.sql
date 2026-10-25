-- Owner: Event Service. Extend the existing type constraint without removing
-- other notification types introduced by independently delivered slices.
DO $$
DECLARE existing_expression text;
BEGIN
 SELECT pg_get_expr(conbin, conrelid) INTO STRICT existing_expression
 FROM pg_constraint
 WHERE conrelid = 'public."EventNotificationOutbox"'::regclass
   AND conname = 'EventNotificationOutbox_type_check';
 ALTER TABLE public."EventNotificationOutbox" DROP CONSTRAINT "EventNotificationOutbox_type_check";
 EXECUTE 'ALTER TABLE public."EventNotificationOutbox" ADD CONSTRAINT "EventNotificationOutbox_type_check" CHECK (('
         || existing_expression || ') OR type = ''event.coordinator-assignment'')';
END $$;
ALTER TABLE public."EventNotificationOutbox" ADD COLUMN held_at timestamptz;

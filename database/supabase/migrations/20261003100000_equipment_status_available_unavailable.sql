-- Equipment status is now just Available | Unavailable.
-- Reservation state belongs to Equipment Availability Service, not the catalogue.
-- Idempotent: only touches rows still marked Reserved.

UPDATE public."Equipment" SET operational_status = 'Unavailable' WHERE operational_status = 'Reserved';

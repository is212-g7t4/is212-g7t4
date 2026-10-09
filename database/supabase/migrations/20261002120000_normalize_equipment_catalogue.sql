-- Normalise the Equipment catalogue to what Equipment Service expects:
--   equipment_type       -> a class name from the Equipment OO model
--   operational_status   -> Available | Unavailable (Reserved was dropped later; see 20261003100000)
-- Idempotent: each UPDATE only touches rows still using the old values.

UPDATE public."Equipment" SET equipment_type = 'Table'       WHERE equipment_type = 'Folding Table';
UPDATE public."Equipment" SET equipment_type = 'Chair'       WHERE equipment_type = 'Stackable Chair';
UPDATE public."Equipment" SET equipment_type = 'Microphone'  WHERE equipment_type = 'Wireless Microphone';
UPDATE public."Equipment" SET equipment_type = 'Speaker'     WHERE equipment_type = 'PA Speaker System';
UPDATE public."Equipment" SET equipment_type = 'LightingKit' WHERE equipment_type = 'Stage Lighting Kit';

UPDATE public."Equipment" SET operational_status = 'Available'   WHERE operational_status = 'Operational';
UPDATE public."Equipment" SET operational_status = 'Unavailable' WHERE operational_status = 'Under Repair';

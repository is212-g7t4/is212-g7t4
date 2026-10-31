"""Database arrange helpers for Equipment Request safety-reset regression tests."""


def mixed_requests(owner):
    """Insert affected and unrelated requests; return IDs and every original persisted field."""
    approved, rejected, pending, unrelated = owner.seed_requests(4)
    owner.db.execute(
        '''UPDATE public."EquipmentRequest" SET status = 'Approved', reviewed_by = %s,
           reviewed_at = '2030-01-01T00:00:00Z' WHERE equipment_request_id = ANY(%s::uuid[])''',
        [owner.reviewer, [approved, unrelated]],
    )
    owner.db.execute(
        '''UPDATE public."EquipmentRequest" SET status = 'Rejected', reviewed_by = %s,
           rejection_reason = 'Unsafe cabling', reviewed_at = '2030-01-01T00:00:00Z'
           WHERE equipment_request_id = %s''',
        [owner.reviewer, rejected],
    )
    return (approved, rejected, pending, unrelated), owner.db.snapshot()

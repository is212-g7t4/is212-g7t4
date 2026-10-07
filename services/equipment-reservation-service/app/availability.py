"""Two-stage availability evaluation for equipment requests (pure logic, no I/O).

Stage 1 is physical: only equipment whose `status` is "Available" can be lent.
Stage 2 is temporal: stock is a shared pool, so what remains is the total less
the quantity other non-rejected events hold over an overlapping window.
`Equipment.operational_status` is never written to by any of this.
"""

# Event statuses whose Approved equipment requests hold stock; pending events hold it once Technical Support approves a line.
RESERVING_EVENT_STATUSES = ("Approved", "Confirmed", "Submitted", "Under Review")


def effective_available_stock(equipment, reserved_quantity):
    """Remaining unallocated quantity; unknown or non-"Available" equipment has none."""
    if equipment is None or equipment.get("status") != "Available":
        return 0
    return max(0, equipment["totalQuantity"] - reserved_quantity)


def evaluate_request(request, equipment, reserved_quantity):
    available = effective_available_stock(equipment, reserved_quantity)
    return {
        "reservedQuantity": reserved_quantity,
        "availableStock": available,
        "isInsufficient": request["quantityRequested"] > available,
    }

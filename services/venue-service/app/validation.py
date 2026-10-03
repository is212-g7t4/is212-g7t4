VALID_STATUSES = ("Available", "Under Maintenance", "Booked")

LABELS = {
    "name": "Venue Name",
    "location": "Location",
    "capacity": "Capacity",
    "accessibility": "Accessibility",
    "facilities": "Facilities",
    "supportedLayouts": "Supported Room Layouts",
    "status": "Operating Status",
}
REQUIRED = {key: LABELS[key] for key in ("name", "location", "capacity", "facilities", "supportedLayouts", "status")}
LIST_FIELDS = ("facilities", "supportedLayouts")


def _blank(value):
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    if isinstance(value, list):
        return len(value) == 0
    return False


def validate(data):
    missing = [label for key, label in REQUIRED.items() if _blank(data.get(key))]
    errors = []

    for key in ("name", "location", "accessibility", "status"):
        if key in data and data[key] is not None and not isinstance(data[key], str):
            errors.append(f"{LABELS[key]} must be text.")

    for key in LIST_FIELDS:
        value = data.get(key)
        if value is None:
            continue
        if not isinstance(value, list) or not all(
            isinstance(item, str) and item.strip() for item in value
        ):
            errors.append(f"{LABELS[key]} must be a list of names.")

    if isinstance(data.get("status"), str) and data["status"].strip() and data["status"] not in VALID_STATUSES:
        errors.append(f"Operating Status must be one of: {', '.join(VALID_STATUSES)}.")

    if missing or errors:
        return missing, errors

    capacity = data["capacity"]
    if (
        not isinstance(capacity, str)
        or not capacity.strip().isdigit()
        or not 1 <= int(capacity) <= 2147483647
    ):
        errors.append("Capacity must be a positive whole number (maximum 2147483647).")

    return missing, errors

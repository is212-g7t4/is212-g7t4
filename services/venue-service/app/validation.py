VALID_STATUSES = ("Available", "Under Maintenance", "Booked")

LABELS = {
    "name": "Venue Name",
    "location": "Location",
    "capacity": "Capacity",
    "accessibility": "Accessibility",
    "facilities": "Facilities",
    "supportedLayouts": "Supported Room Layouts",
    "status": "Operating Status",
    "setupTimeMinutes": "Setup Time",
    "turnaroundTimeMinutes": "Turnaround Time",
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

    for key in ("setupTimeMinutes", "turnaroundTimeMinutes"):
        if key not in data:
            continue
        value = data[key]
        valid = (
            isinstance(value, int)
            and not isinstance(value, bool)
            and 0 <= value <= 2147483647
        ) or (
            isinstance(value, str)
            and value.strip().isdigit()
            and len(value.strip()) <= 10
            and 0 <= int(value.strip()) <= 2147483647
        )
        if not valid:
            errors.append(
                f"{LABELS[key]} must be a non-negative whole number of minutes "
                "(maximum 2147483647)."
            )

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


# SCRUM-167: venue safety information, two free-text fields replaced together.
SAFETY_LABELS = {
    "emergencyAccessDetails": "Emergency Access Details",
    "knownRestrictions": "Known Restrictions",
}
SAFETY_MAX_LENGTH = 2000


def validate_safety_info(data):
    """Return ({key: text or None}, errors). Blank text is stored as NULL."""
    if not isinstance(data, dict):
        return {}, ["Send a JSON object."]
    values, errors = {}, []
    for key, label in SAFETY_LABELS.items():
        if key not in data:
            errors.append(f"{label} is required (send null to clear it).")
            continue
        value = data[key]
        if value is not None and not isinstance(value, str):
            errors.append(f"{label} must be text.")
            continue
        text = (value or "").strip()
        if len(text) > SAFETY_MAX_LENGTH:
            errors.append(f"{label} must be at most {SAFETY_MAX_LENGTH} characters.")
            continue
        values[key] = text or None
    return values, errors

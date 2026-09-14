from datetime import datetime

REQUIRED = {
    "eventName": "Event Name",
    "description": "Description",
    "purpose": "Purpose",
    "preferredStartDate": "Preferred Start Date & Time",
    "preferredEndDate": "Preferred End Date & Time",
    "expectedAttendance": "Expected Attendance",
}
OPTIONAL = ("venueRequirements", "accessibilityNeeds", "equipmentRequirements", "registrationNeeds")


def validate(data):
    missing = [label for key, label in REQUIRED.items()
               if data.get(key) is None or (isinstance(data[key], str) and not data[key].strip())]
    errors = []
    for key in (*REQUIRED, *OPTIONAL):
        if key in data and not isinstance(data[key], str):
            errors.append(f"{REQUIRED.get(key, key)} must be text.")
    if missing or errors:
        return missing, errors
    attendance = data["expectedAttendance"].strip()
    if (not attendance.isascii() or not attendance.isdigit() or len(attendance) > 10
            or not 1 <= int(attendance) <= 2147483647):
        errors.append("Expected Attendance must be a positive whole number (maximum 2147483647).")
    try:
        start, end = (datetime.fromisoformat(data[key]) for key in ("preferredStartDate", "preferredEndDate"))
        if start.tzinfo or end.tzinfo or "T" not in data["preferredStartDate"] or "T" not in data["preferredEndDate"]:
            raise ValueError
        if end <= start:
            errors.append("Preferred End Date & Time must be after the start.")
    except ValueError:
        errors.append("Preferred dates must be valid local dates and times.")
    return missing, errors


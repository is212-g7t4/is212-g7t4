from datetime import datetime

REQUIRED = {
    "eventName": "Event Name",
    "description": "Description",
    "purpose": "Purpose",
    "preferredStartDate": "Preferred Start Date & Time",
    "preferredEndDate": "Preferred End Date & Time",
    "expectedAttendance": "Expected Attendance",
}
OPTIONAL = (
    "venueRequirements",
    "accessibilityNeeds",
    "equipmentRequirements",
    "registrationNeeds",
    "withdrawalDeadline",
)
ATTENDANCE_ERROR = (
    "Expected Attendance must be a positive whole number (maximum 2147483647)."
)
DATE_ERROR = "Preferred dates must be valid local dates and times."
PERIOD_ERROR = "Preferred End Date & Time must be after the start."
WITHDRAWAL_DEADLINE_ERROR = (
    "Withdrawal Deadline must be a valid local date and time no later than the event start."
)


def _blank(data, key):
    return data.get(key) is None or (
        isinstance(data[key], str) and not data[key].strip()
    )


def _type_errors(data):
    return [
        f"{REQUIRED.get(key, key)} must be text."
        for key in (*REQUIRED, *OPTIONAL)
        if key in data and not isinstance(data[key], str)
    ]


def _attendance_errors(value):
    attendance = value.strip()
    if (
        not attendance.isascii()
        or not attendance.isdigit()
        or len(attendance) > 10
        or not 1 <= int(attendance) <= 2147483647
    ):
        return [ATTENDANCE_ERROR]
    return []


def _local_datetime(value):
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo or "T" not in value:
        raise ValueError
    return parsed


def _period_errors(start, end):
    try:
        start, end = _local_datetime(start), _local_datetime(end)
    except ValueError:
        return [DATE_ERROR]
    return [PERIOD_ERROR] if end <= start else []


def _withdrawal_deadline_errors(deadline, start):
    if _blank({"deadline": deadline}, "deadline"):
        return []
    try:
        deadline_value = _local_datetime(deadline)
        start_value = _local_datetime(start)
    except (ValueError, TypeError):
        return [WITHDRAWAL_DEADLINE_ERROR]
    return [WITHDRAWAL_DEADLINE_ERROR] if deadline_value > start_value else []


def validate(data):
    missing = [label for key, label in REQUIRED.items() if _blank(data, key)]
    errors = _type_errors(data)
    if missing or errors:
        return missing, errors
    errors = _attendance_errors(data["expectedAttendance"])
    errors += _period_errors(data["preferredStartDate"], data["preferredEndDate"])
    errors += _withdrawal_deadline_errors(
        data.get("withdrawalDeadline", ""), data["preferredStartDate"]
    )
    return missing, errors


def validate_draft(data):
    """A draft needs only its name; whatever else is filled in must be well formed.

    Attendance and the dates are typed columns, so a malformed value has to be
    refused here rather than surfacing as a database error.
    """
    missing = [REQUIRED["eventName"]] if _blank(data, "eventName") else []
    errors = _type_errors(data)
    if errors:
        return missing, errors
    if not _blank(data, "expectedAttendance"):
        errors += _attendance_errors(data["expectedAttendance"])
    start_blank = _blank(data, "preferredStartDate")
    end_blank = _blank(data, "preferredEndDate")
    if not start_blank and not end_blank:
        errors += _period_errors(data["preferredStartDate"], data["preferredEndDate"])
    elif not start_blank or not end_blank:
        try:
            _local_datetime(data["preferredEndDate" if start_blank else "preferredStartDate"])
        except ValueError:
            errors.append(DATE_ERROR)
    if not _blank(data, "withdrawalDeadline"):
        if start_blank:
            try:
                _local_datetime(data["withdrawalDeadline"])
            except (ValueError, TypeError):
                errors.append(WITHDRAWAL_DEADLINE_ERROR)
        else:
            errors += _withdrawal_deadline_errors(
                data["withdrawalDeadline"], data["preferredStartDate"]
            )
    return missing, errors

import os
import hmac
from datetime import datetime, timedelta
from uuid import UUID

import psycopg2
from dotenv import load_dotenv
from flask import Flask, g, jsonify, request

from app.calendar import parse_boundary
from app.models import (
    BookingAlreadyDecidedError,
    BookingConflictError,
    BookingNotFoundError,
    BookingStateError,
    CalendarDataError,
    HoldConflictError,
    HoldVenueNotFoundError,
    cancel_booking,
    create_booking,
    create_hold,
    decide_booking,
    get_booking,
    list_active_holds,
    list_bookings,
    list_event_bookings,
    list_hold_reminders,
    list_window_bookings,
    list_window_closures,
    reconcile_legacy_conflicts,
    reset_safety_bookings,
    update_booking,
    _shift,
)
from app.auth import authenticate

# SCRUM-26: the longest window the venue search will answer for. Same spirit
# as the calendar's 42-day bound — an unbounded range is an unbounded read.
MAX_WINDOW = timedelta(days=42)

# SCRUM-29 AC4: matches the frontend RejectionDialog's maxLength.
MAX_REJECTION_REASON = 500

load_dotenv()


def _parse_uuid(value):
    try:
        return str(UUID(value))
    except (ValueError, TypeError, AttributeError):
        return None


def _parse_datetime(value):
    try:
        parsed = datetime.fromisoformat(value)
        if parsed.tzinfo or "T" not in value:
            return None
        return parsed
    except (ValueError, TypeError):
        return None


def _parse_rejection_reason(value):
    """Return the stripped reason, or None when it is missing or invalid."""
    if not isinstance(value, str):
        return None
    reason = value.strip()
    return reason if 0 < len(reason) <= MAX_REJECTION_REASON else None


def _parse_buffer_minutes(value, default=0):
    if value is None:
        return default
    if isinstance(value, bool):
        return None
    try:
        text = str(value).strip()
        if not text.isdigit():
            return None
        minutes = int(text)
        return minutes if 0 <= minutes <= 2147483647 else None
    except (TypeError, ValueError):
        return None


BOOKING_VIEW_ROLES = (
    "Event Coordinator", "Event Coordinator Lead", "Venue Staff", "Technical Support", "Technical Support Staff",
)


def _may_view_bookings():
    """SCRUM-9: booking records and holds are for internal roles; internal callers have no user."""
    return g.user_id is None or g.role in BOOKING_VIEW_ROLES


def create_app(config=None):
    app = Flask(__name__)
    app.before_request(authenticate)
    app.config.from_mapping(
        DATABASE_URL=os.getenv("DATABASE_URL"),
        CLOSURE_CONFIRMATION_KEY=os.getenv("CLOSURE_CONFIRMATION_KEY"),
        INTERNAL_SERVICE_TOKEN=os.getenv("INTERNAL_SERVICE_TOKEN"),
        # The Vite dev server is pinned to 5174 (strictPort in
        # vite.config.ts), so that is the origin the browser sends.
        FRONTEND_ORIGIN=os.getenv("FRONTEND_ORIGIN") or "http://localhost:5174",
    )
    app.config.update(config or {})

    @app.after_request
    def cors(response):
        origin = request.headers.get("Origin")
        configured_origin = app.config["FRONTEND_ORIGIN"]
        allowed_origins = {configured_origin}
        if configured_origin:
            allowed_origins.add(configured_origin.replace("localhost", "127.0.0.1"))
            allowed_origins.add(configured_origin.replace("127.0.0.1", "localhost"))
        if origin in allowed_origins:
            response.headers["Access-Control-Allow-Origin"] = origin
            response.headers["Vary"] = "Origin"
            # Every browser call carries a bearer token, so every path needs the preflight answer.
            response.headers["Access-Control-Allow-Methods"] = "GET, OPTIONS, POST"
            response.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization"
        return response

    @app.errorhandler(CalendarDataError)
    @app.errorhandler(psycopg2.Error)
    def database_failure(error):
        return jsonify(message="Unable to save or load venue bookings."), 503

    @app.get("/health")
    def health():
        return jsonify(status="ok")

    @app.get("/venue-bookings")
    def get_bookings():
        if g.role not in {
            "Event Coordinator",
            "Event Coordinator Lead",
            "Venue Staff",
            "Technical Support",
            "Technical Support Staff",
        }:
            return jsonify(message="Internal roles only."), 403
        if any(
            len(request.args.getlist(key)) != 1
            for key in ("venueId", "dateFrom", "dateTo")
        ):
            return jsonify(
                message="Provide each calendar query parameter exactly once."
            ), 400
        venue_id = _parse_uuid(request.args.get("venueId"))
        date_from = (
            parse_boundary(request.args["dateFrom"])
            if request.args.get("dateFrom")
            else None
        )
        date_to = (
            parse_boundary(request.args["dateTo"])
            if request.args.get("dateTo")
            else None
        )
        setup_time = _parse_buffer_minutes(request.args.get("setupTimeMinutes"))
        turnaround_time = _parse_buffer_minutes(
            request.args.get("turnaroundTimeMinutes")
        )
        if (
            not venue_id
            or not date_from
            or not date_to
            or setup_time is None
            or turnaround_time is None
            or not timedelta(0) < date_to - date_from <= timedelta(days=42)
        ):
            return jsonify(
                message="Require venueId UUID and dateFrom < dateTo, maximum 42 days."
            ), 400
        if not app.config["DATABASE_URL"]:
            return jsonify(
                message="DATABASE_URL is not configured for Venue Availability Service."
            ), 503
        return jsonify(
            bookings=list_bookings(
                app.config["DATABASE_URL"],
                venue_id,
                date_from,
                date_to,
                setup_time,
                turnaround_time,
            ),
            closures=list_window_closures(
                app.config["DATABASE_URL"], date_from, date_to, venue_id
            ),
        )

    @app.get("/venue-bookings/window")
    def get_window_bookings():
        """SCRUM-26: every venue's bookings overlapping one window.

        A service-to-service read for Venue Booking Service's venue search,
        which needs the whole catalogue's bookings at once; `GET
        /venue-bookings` answers for a single venue, as a calendar grid needs.

        Not role-gated: the caller is a composite (forwarding the signed-in
        user's token), not a browser. It exposes no more than the calendar
        read does, and the composite does its own role check.
        """
        if any(len(request.args.getlist(key)) != 1 for key in ("dateFrom", "dateTo")):
            return jsonify(message="Provide dateFrom and dateTo exactly once."), 400
        date_from = parse_boundary(request.args["dateFrom"])
        date_to = parse_boundary(request.args["dateTo"])
        padding_minutes = _parse_buffer_minutes(
            request.args.get("paddingMinutes")
        )
        if (
            not date_from
            or not date_to
            or padding_minutes is None
            or not timedelta(0) < date_to - date_from <= MAX_WINDOW
        ):
            return jsonify(
                message="Require dateFrom < dateTo as ISO date-times, maximum 42 days."
            ), 400
        if not app.config["DATABASE_URL"]:
            return jsonify(
                message="DATABASE_URL is not configured for Venue Availability Service."
            ), 503
        return jsonify(
            bookings=list_window_bookings(
                app.config["DATABASE_URL"], date_from, date_to, padding_minutes
            ),
            closures=list_window_closures(
                app.config["DATABASE_URL"],
                _shift(date_from, -padding_minutes),
                _shift(date_to, padding_minutes),
            ),
        )

    @app.get("/venue-holds")
    def get_holds():
        if not _may_view_bookings():
            return jsonify(message="Internal roles only."), 403
        if not app.config["DATABASE_URL"]:
            return jsonify(
                message="DATABASE_URL is not configured for Venue Availability Service."
            ), 503
        return jsonify(holds=list_active_holds(app.config["DATABASE_URL"]))

    @app.get("/venue-holds/reminders")
    def get_hold_reminders():
        """Holds expiring within 3 days that were placed for the calling coordinator."""
        coordinator_id = g.user_id
        if not coordinator_id:
            return jsonify(message="Sign in to continue."), 401
        if g.role not in {"Event Coordinator", "Event Coordinator Lead"}:
            return jsonify(message="Event Coordinator role is required."), 403
        if not app.config["DATABASE_URL"]:
            return jsonify(
                message="DATABASE_URL is not configured for Venue Availability Service."
            ), 503
        return jsonify(
            reminders=list_hold_reminders(app.config["DATABASE_URL"], coordinator_id)
        )

    @app.post("/venue-holds")
    def place_hold():
        staff_id = g.user_id
        if not staff_id:
            return jsonify(message="Sign in to continue."), 401
        if g.role != "Venue Staff":
            return jsonify(message="Venue Staff role is required to place a hold."), 403
        data = request.get_json(silent=True)
        if not isinstance(data, dict):
            return jsonify(message="Send a JSON object."), 400
        venue_id = _parse_uuid(data.get("venueId"))
        expires_at = _parse_datetime(data.get("expiresAt"))
        setup_time = _parse_buffer_minutes(data.get("setupTimeMinutes"))
        turnaround_time = _parse_buffer_minutes(data.get("turnaroundTimeMinutes"))
        if (
            not venue_id
            or not expires_at
            or setup_time is None
            or turnaround_time is None
        ):
            return jsonify(
                message=(
                    "venueId and expiresAt must be valid, and venue buffer times "
                    "must be non-negative whole minutes."
                )
            ), 400
        held_for = None
        if data.get("coordinatorId") is not None:
            held_for = _parse_uuid(data["coordinatorId"])
            if not held_for:
                return jsonify(message="coordinatorId must be a valid id."), 400
        from app.calendar import SINGAPORE

        now = datetime.now(SINGAPORE).replace(tzinfo=None)
        if expires_at <= now:
            return jsonify(message="Hold expiry must be in the future."), 400
        if not app.config["DATABASE_URL"]:
            return jsonify(
                message="DATABASE_URL is not configured for Venue Availability Service."
            ), 503
        try:
            hold = create_hold(
                app.config["DATABASE_URL"],
                venue_id,
                expires_at,
                staff_id,
                held_for,
                setup_time,
                turnaround_time,
            )
        except HoldVenueNotFoundError:
            return jsonify(message="Venue not found."), 404
        except HoldConflictError:
            return jsonify(
                message="This hold overlaps an existing booking or active hold."
            ), 409
        return jsonify(hold=hold), 201

    @app.post("/venue-bookings")
    def create_booking_route():
        data = request.get_json(silent=True)
        if not isinstance(data, dict):
            return jsonify(message="Send a JSON object."), 400

        event_id = _parse_uuid(data.get("eventId"))
        venue_id = _parse_uuid(data.get("venueId"))
        # The coordinator whose token Venue Booking Service forwards.
        requested_by = g.user_id
        if not requested_by:
            return jsonify(message="Sign in to continue."), 401
        start = _parse_datetime(data.get("requestedStartTime"))
        end = _parse_datetime(data.get("requestedEndTime"))
        required_capacity = data.get("requiredCapacity")
        venue_requirements = data.get("venueRequirements")
        setup_time = _parse_buffer_minutes(data.get("setupTimeMinutes"))
        turnaround_time = _parse_buffer_minutes(data.get("turnaroundTimeMinutes"))
        if not event_id or not venue_id:
            return jsonify(message="eventId and venueId must be valid ids."), 400
        if not start or not end:
            return jsonify(
                message="requestedStartTime and requestedEndTime must be valid dates and times."
            ), 400
        if end <= start:
            return jsonify(
                message="requestedEndTime must be after requestedStartTime."
            ), 400
        if (
            isinstance(required_capacity, bool)
            or not isinstance(required_capacity, int)
            or not 1 <= required_capacity <= 2147483647
        ):
            return jsonify(
                message="requiredCapacity must be a positive whole number."
            ), 400
        if not isinstance(venue_requirements, str):
            return jsonify(message="venueRequirements must be text."), 400
        if setup_time is None or turnaround_time is None:
            return jsonify(
                message="Venue buffer times must be non-negative whole minutes."
            ), 400
        if not app.config["DATABASE_URL"]:
            return jsonify(
                message="DATABASE_URL is not configured for Venue Availability Service."
            ), 503

        try:
            booking = create_booking(
                app.config["DATABASE_URL"],
                event_id,
                venue_id,
                start,
                end,
                required_capacity,
                venue_requirements.strip(),
                requested_by,
                setup_time,
                turnaround_time,
            )
        except BookingConflictError as error:
            return jsonify(
                message="This venue is unavailable for the requested time.",
                code="VENUE_UNAVAILABLE",
                conflictTypes=error.conflict_types,
            ), 409
        return jsonify(booking), 201

    @app.post("/events/<uuid:event_id>/venue-bookings/safety-reset")
    def safety_reset_bookings(event_id):
        token = app.config["INTERNAL_SERVICE_TOKEN"]
        if not token:
            return jsonify(message="Internal service authentication is not configured."), 503
        if not hmac.compare_digest(token, request.headers.get("X-Internal-Service-Token", "")):
            return jsonify(message="Internal service credentials are required."), 403
        data = request.get_json(silent=True)
        raw_ids = data.get("bookingIds") if isinstance(data, dict) else None
        if not isinstance(raw_ids, list) or not 1 <= len(raw_ids) <= 500:
            return jsonify(message="Provide 1 to 500 bookingIds."), 400
        booking_ids = [_parse_uuid(value) for value in raw_ids]
        if None in booking_ids or len(set(booking_ids)) != len(booking_ids):
            return jsonify(message="bookingIds must be distinct valid UUIDs."), 400
        if not app.config["DATABASE_URL"]:
            return jsonify(message="DATABASE_URL is not configured."), 503
        try:
            return jsonify(bookings=reset_safety_bookings(app.config["DATABASE_URL"], str(event_id), booking_ids))
        except BookingNotFoundError:
            return jsonify(message="Every booking must belong to this event."), 404

    @app.get("/events/<uuid:event_id>/venue-bookings")
    def get_event_bookings(event_id):
        if not app.config["DATABASE_URL"]:
            return jsonify(
                message="DATABASE_URL is not configured for Venue Availability Service."
            ), 503
        bookings = list_event_bookings(app.config["DATABASE_URL"], str(event_id))
        if g.role == "Attendee":
            # SCRUM-9: an Attendee only needs the confirmed venue, not pending or rejected requests.
            bookings = [b for b in bookings if b["status"] == "Approved"]
        return jsonify(bookings=bookings)

    @app.get("/venue-bookings/<uuid:booking_id>")
    def get_booking_route(booking_id):
        if not _may_view_bookings():
            return jsonify(message="Internal roles only."), 403
        if not app.config["DATABASE_URL"]:
            return jsonify(
                message="DATABASE_URL is not configured for Venue Availability Service."
            ), 503
        try:
            booking = get_booking(app.config["DATABASE_URL"], str(booking_id))
        except BookingNotFoundError:
            return jsonify(message="Venue booking not found."), 404
        return jsonify(booking)

    @app.patch("/venue-bookings/<uuid:booking_id>")
    def update_booking_route(booking_id):
        data = request.get_json(silent=True)
        if not isinstance(data, dict):
            return jsonify(message="Send a JSON object."), 400

        event_id = _parse_uuid(data.get("eventId"))
        venue_id = _parse_uuid(data.get("venueId"))
        start = _parse_datetime(data.get("requestedStartTime"))
        end = _parse_datetime(data.get("requestedEndTime"))
        required_capacity = data.get("requiredCapacity")
        venue_requirements = data.get("venueRequirements")
        setup_time = _parse_buffer_minutes(data.get("setupTimeMinutes"))
        turnaround_time = _parse_buffer_minutes(data.get("turnaroundTimeMinutes"))
        if not event_id or not venue_id:
            return jsonify(message="eventId and venueId must be valid ids."), 400
        if not start or not end or end <= start:
            return jsonify(
                message="Booking dates must be valid, with the end after the start."
            ), 400
        if (
            isinstance(required_capacity, bool)
            or not isinstance(required_capacity, int)
            or not 1 <= required_capacity <= 2147483647
        ):
            return jsonify(
                message="requiredCapacity must be a positive whole number."
            ), 400
        if not isinstance(venue_requirements, str):
            return jsonify(message="venueRequirements must be text."), 400
        if setup_time is None or turnaround_time is None:
            return jsonify(
                message="Venue buffer times must be non-negative whole minutes."
            ), 400
        if not app.config["DATABASE_URL"]:
            return jsonify(
                message="DATABASE_URL is not configured for Venue Availability Service."
            ), 503

        try:
            booking = update_booking(
                app.config["DATABASE_URL"],
                str(booking_id),
                event_id,
                venue_id,
                start,
                end,
                required_capacity,
                venue_requirements.strip(),
                setup_time,
                turnaround_time,
            )
        except BookingNotFoundError:
            return jsonify(message="Venue booking not found for this event."), 404
        except BookingStateError:
            return (
                jsonify(
                    message="Cancelled or Rejected venue bookings cannot be modified.",
                    code="BOOKING_IMMUTABLE",
                ),
                409,
            )
        except BookingConflictError as error:
            return jsonify(
                message="This venue is unavailable for the requested time.",
                code="VENUE_UNAVAILABLE",
                conflictTypes=error.conflict_types,
            ), 409
        return jsonify(booking), 200

    @app.patch("/venue-bookings/<uuid:booking_id>/cancel")
    def cancel_booking_route(booking_id):
        data = request.get_json(silent=True)
        event_id = _parse_uuid(data.get("eventId")) if isinstance(data, dict) else None
        if not event_id:
            return jsonify(message="eventId must be a valid id."), 400
        if not app.config["DATABASE_URL"]:
            return jsonify(
                message="DATABASE_URL is not configured for Venue Availability Service."
            ), 503
        try:
            booking = cancel_booking(
                app.config["DATABASE_URL"], str(booking_id), event_id
            )
        except BookingStateError:
            return (
                jsonify(
                    message="Rejected venue bookings cannot be cancelled.",
                    code="BOOKING_IMMUTABLE",
                ),
                409,
            )
        except BookingNotFoundError:
            return jsonify(message="Venue booking not found for this event."), 404
        return jsonify(booking), 200

    @app.patch("/venue-bookings/<uuid:booking_id>/approve")
    def approve_booking(booking_id):
        return _decide(booking_id, "Approved")

    @app.patch("/venue-bookings/<uuid:booking_id>/reject")
    def reject_booking(booking_id):
        return _decide(booking_id, "Rejected")

    def _decide(booking_id, status):
        data = request.get_json(silent=True)
        # The Venue Staff reviewer whose token Venue Booking Service forwards.
        reviewed_by = g.user_id
        setup_time = _parse_buffer_minutes(
            data.get("setupTimeMinutes") if isinstance(data, dict) else None
        )
        turnaround_time = _parse_buffer_minutes(
            data.get("turnaroundTimeMinutes") if isinstance(data, dict) else None
        )
        if not reviewed_by:
            return jsonify(message="Sign in to continue."), 401
        if setup_time is None or turnaround_time is None:
            return jsonify(
                message="Venue buffer times must be non-negative whole minutes."
            ), 400
        # SCRUM-29 AC4: a rejection must explain itself to the coordinator.
        # A reason sent with an approval is ignored, not stored.
        rejection_reason = None
        if status == "Rejected":
            rejection_reason = _parse_rejection_reason(data.get("rejectionReason"))
            if rejection_reason is None:
                return jsonify(
                    message="A reason is required to reject a venue request.",
                    code="REJECTION_REASON_REQUIRED",
                ), 400
        if not app.config["DATABASE_URL"]:
            return jsonify(
                message="DATABASE_URL is not configured for Venue Availability Service."
            ), 503
        try:
            booking = decide_booking(
                app.config["DATABASE_URL"],
                str(booking_id),
                reviewed_by,
                status,
                setup_time,
                turnaround_time,
                rejection_reason,
            )
        except BookingNotFoundError:
            return jsonify(message="Venue booking not found."), 404
        except BookingAlreadyDecidedError:
            return jsonify(
                message="This venue request has already been decided.",
                code="BOOKING_ALREADY_DECIDED",
            ), 409
        except BookingStateError:
            return (
                jsonify(
                    message="Cancelled or Rejected venue bookings cannot be reviewed.",
                    code="BOOKING_IMMUTABLE",
                ),
                409,
            )
        except BookingConflictError as error:
            return jsonify(
                message="This venue is unavailable for the requested time.",
                code="VENUE_UNAVAILABLE",
                conflictTypes=error.conflict_types,
            ), 409
        return jsonify(booking), 200

    @app.post("/venues/<uuid:venue_id>/legacy-conflicts/reconcile")
    def reconcile_legacy_conflicts_route(venue_id):
        data = request.get_json(silent=True)
        setup_time = _parse_buffer_minutes(
            data.get("setupTimeMinutes") if isinstance(data, dict) else None
        )
        turnaround_time = _parse_buffer_minutes(
            data.get("turnaroundTimeMinutes") if isinstance(data, dict) else None
        )
        if not isinstance(data, dict) or setup_time is None or turnaround_time is None:
            return jsonify(
                message="Venue buffer times must be non-negative whole minutes."
            ), 400
        if not app.config["DATABASE_URL"]:
            return jsonify(
                message="DATABASE_URL is not configured for Venue Availability Service."
            ), 503
        result = reconcile_legacy_conflicts(
            app.config["DATABASE_URL"],
            str(venue_id),
            setup_time,
            turnaround_time,
        )
        return jsonify(result)

    from app.closures import bp as closures_bp

    app.register_blueprint(closures_bp)
    from app.outbox import bp as outbox_bp
    app.register_blueprint(outbox_bp)
    return app

import os
from datetime import datetime, timedelta
from uuid import UUID

import psycopg2
from dotenv import load_dotenv
from flask import Flask, jsonify, request

from app.calendar import parse_boundary
from app.models import (
    BookingConflictError,
    BookingNotFoundError,
    CalendarDataError,
    HoldConflictError,
    HoldVenueNotFoundError,
    create_booking,
    create_hold,
    decide_booking,
    list_active_holds,
    list_bookings,
    list_window_bookings,
)

# SCRUM-26: the longest window the venue search will answer for. Same spirit
# as the calendar's 42-day bound — an unbounded range is an unbounded read.
MAX_WINDOW = timedelta(days=42)

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


def create_app(config=None):
    app = Flask(__name__)
    app.config.from_mapping(
        DATABASE_URL=os.getenv("DATABASE_URL"),
        CALENDAR_DEV_MODE=os.getenv("CALENDAR_DEV_MODE") == "true",
        # The Vite dev server is pinned to 5174 (strictPort in
        # vite.config.ts), so that is the origin the browser sends.
        FRONTEND_ORIGIN=os.getenv("FRONTEND_ORIGIN", "http://localhost:5174"),
    )
    app.config.update(config or {})

    @app.after_request
    def cors(response):
        origin = request.headers.get("Origin")
        if origin == app.config["FRONTEND_ORIGIN"]:
            response.headers["Access-Control-Allow-Origin"] = origin
            response.headers["Vary"] = "Origin"
            if request.path in {"/venue-bookings", "/venue-holds"}:
                response.headers["Access-Control-Allow-Methods"] = "GET, OPTIONS, POST"
                response.headers["Access-Control-Allow-Headers"] = (
                    "Content-Type, X-Dev-User-Id, X-Dev-Role"
                )
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
        if app.config["CALENDAR_DEV_MODE"] is not True:
            return jsonify(message="Calendar DEV mode is disabled."), 503
        role = request.headers.get("X-Dev-Role")
        if not _parse_uuid(request.headers.get("X-Dev-User-Id")) or not role:
            return jsonify(message="DEV user UUID and role headers are required."), 401
        if role not in {
            "Event Coordinator",
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
        if (
            not venue_id
            or not date_from
            or not date_to
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
                app.config["DATABASE_URL"], venue_id, date_from, date_to
            )
        )

    @app.get("/venue-bookings/window")
    def get_window_bookings():
        """SCRUM-26: every venue's bookings overlapping one window.

        A service-to-service read for Venue Booking Service's venue search,
        which needs the whole catalogue's bookings at once; `GET
        /venue-bookings` answers for a single venue, as a calendar grid needs.

        Deliberately not behind CALENDAR_DEV_MODE or the X-Dev-* headers:
        those simulate the browser's user switcher, and this caller is a
        composite, not a browser. It exposes no more than the calendar read
        does, and the composite does its own role check.
        """
        if any(len(request.args.getlist(key)) != 1 for key in ("dateFrom", "dateTo")):
            return jsonify(
                message="Provide dateFrom and dateTo exactly once."
            ), 400
        date_from = parse_boundary(request.args["dateFrom"])
        date_to = parse_boundary(request.args["dateTo"])
        if (
            not date_from
            or not date_to
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
                app.config["DATABASE_URL"], date_from, date_to
            )
        )

    @app.get("/venue-holds")
    def get_holds():
        if not app.config["DATABASE_URL"]:
            return jsonify(
                message="DATABASE_URL is not configured for Venue Availability Service."
            ), 503
        return jsonify(holds=list_active_holds(app.config["DATABASE_URL"]))

    @app.post("/venue-holds")
    def place_hold():
        if app.config["CALENDAR_DEV_MODE"] is not True:
            return jsonify(message="Venue hold DEV mode is disabled."), 503
        staff_id = _parse_uuid(request.headers.get("X-Dev-User-Id"))
        if not staff_id or not request.headers.get("X-Dev-Role"):
            return jsonify(message="DEV user UUID and role headers are required."), 401
        if request.headers.get("X-Dev-Role") != "Venue Staff":
            return jsonify(message="Venue Staff role is required to place a hold."), 403
        data = request.get_json(silent=True)
        if not isinstance(data, dict):
            return jsonify(message="Send a JSON object."), 400
        venue_id = _parse_uuid(data.get("venueId"))
        expires_at = _parse_datetime(data.get("expiresAt"))
        if not venue_id or not expires_at:
            return jsonify(
                message="venueId must be a valid id and expiresAt a local ISO date-time."
            ), 400
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
                app.config["DATABASE_URL"], venue_id, expires_at, staff_id
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
        requested_by = _parse_uuid(data.get("requestedBy"))
        start = _parse_datetime(data.get("requestedStartTime"))
        end = _parse_datetime(data.get("requestedEndTime"))
        if not event_id or not venue_id or not requested_by:
            return jsonify(
                message="eventId, venueId and requestedBy must be valid ids."
            ), 400
        if not start or not end:
            return jsonify(
                message="requestedStartTime and requestedEndTime must be valid dates and times."
            ), 400
        if end <= start:
            return jsonify(
                message="requestedEndTime must be after requestedStartTime."
            ), 400
        if not app.config["DATABASE_URL"]:
            return jsonify(
                message="DATABASE_URL is not configured for Venue Availability Service."
            ), 503

        try:
            booking = create_booking(
                app.config["DATABASE_URL"], event_id, venue_id, start, end, requested_by
            )
        except BookingConflictError:
            return jsonify(
                message="This venue is already booked for the requested time."
            ), 409
        return jsonify(booking), 201

    @app.patch("/venue-bookings/<uuid:booking_id>/approve")
    def approve_booking(booking_id):
        return _decide(booking_id, "Approved")

    @app.patch("/venue-bookings/<uuid:booking_id>/reject")
    def reject_booking(booking_id):
        return _decide(booking_id, "Rejected")

    def _decide(booking_id, status):
        data = request.get_json(silent=True)
        reviewed_by = (
            _parse_uuid(data.get("reviewedBy")) if isinstance(data, dict) else None
        )
        if not reviewed_by:
            return jsonify(message="reviewedBy must be a valid id."), 400
        if not app.config["DATABASE_URL"]:
            return jsonify(
                message="DATABASE_URL is not configured for Venue Availability Service."
            ), 503
        try:
            booking = decide_booking(
                app.config["DATABASE_URL"], str(booking_id), reviewed_by, status
            )
        except BookingNotFoundError:
            return jsonify(message="Venue booking not found."), 404
        except BookingConflictError:
            return jsonify(
                message="This venue is already booked for the requested time."
            ), 409
        return jsonify(booking), 200

    return app

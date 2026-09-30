import os
from datetime import datetime
from uuid import UUID

import psycopg2
from dotenv import load_dotenv
from flask import Flask, jsonify, request

load_dotenv()

from app.models import (
    BookingConflictError,
    BookingNotFoundError,
    create_booking,
    decide_booking,
    list_bookings,
)


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
        FRONTEND_ORIGIN=os.getenv("FRONTEND_ORIGIN", "http://localhost:5173"),
    )
    app.config.update(config or {})

    @app.after_request
    def cors(response):
        origin = request.headers.get("Origin")
        if origin == app.config["FRONTEND_ORIGIN"]:
            response.headers["Access-Control-Allow-Origin"] = origin
            response.headers["Vary"] = "Origin"
        return response

    @app.errorhandler(psycopg2.Error)
    def database_failure(error):
        return jsonify(message="Unable to save or load venue bookings."), 503

    @app.get("/health")
    def health():
        return jsonify(status="ok")

    @app.get("/venue-bookings")
    def get_bookings():
        venue_id = request.args.get("venueId")
        date_from = (
            _parse_datetime(request.args["dateFrom"])
            if request.args.get("dateFrom")
            else None
        )
        date_to = (
            _parse_datetime(request.args["dateTo"])
            if request.args.get("dateTo")
            else None
        )
        if not app.config["DATABASE_URL"]:
            return jsonify(
                message="DATABASE_URL is not configured for Venue Availability Service."
            ), 503
        return jsonify(
            bookings=list_bookings(
                app.config["DATABASE_URL"], venue_id, date_from, date_to
            )
        )

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

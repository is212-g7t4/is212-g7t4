"""SCRUM-170 closure routes; DEV headers are explicitly spoofable."""

from uuid import UUID
from flask import Blueprint, current_app, jsonify, request

bp = Blueprint("closures", __name__)


@bp.before_request
def staff_only():
    if request.method == "OPTIONS":
        return None
    if current_app.config["VENUE_CLOSURE_DEV_MODE"] is not True:
        return jsonify(message="Venue closure DEV mode is disabled."), 503
    try:
        UUID(request.headers.get("X-Dev-User-Id", ""))
    except ValueError:
        return jsonify(message="DEV user UUID is required."), 401
    role = request.headers.get("X-Dev-Role")
    if not role:
        return jsonify(message="DEV role is required."), 401
    if role != "Venue Staff":
        return jsonify(message="Venue Staff role is required."), 403


@bp.post("/venue-closures/preview")
def preview():
    from app.closure_contract import create_input
    from app import closure_store
    import psycopg2

    try:
        data = create_input(request.get_json(silent=True))
    except (ValueError, OverflowError) as error:
        return jsonify(message=str(error)), 400
    dsn = current_app.config.get("DATABASE_URL")
    key = current_app.config.get("CLOSURE_CONFIRMATION_KEY")
    if not dsn or not isinstance(key, str) or len(key.encode()) < 32:
        return jsonify(message="Closure confirmation is not configured."), 503
    try:
        return jsonify(
            closure_store.preview(
                dsn, data, str(UUID(request.headers["X-Dev-User-Id"])), key
            )
        )
    except psycopg2.Error:
        return jsonify(message="Unable to load closure impact."), 503


@bp.route("/venue-closures", methods=["GET", "POST"])
@bp.get("/venue-closures/<closure_id>")
def closures(closure_id=None):
    from app.closure_contract import confirmation_input, uuid_value, list_input

    try:
        if request.method == "POST":
            data, token = confirmation_input(request.get_json(silent=True))
        elif closure_id is not None:
            closure_id = uuid_value(closure_id)
        else:
            venue, limit, after = list_input(request.args)
    except (ValueError, OverflowError) as error:
        return jsonify(message=str(error)), 400
    import psycopg2
    from app import closure_store

    dsn = current_app.config.get("DATABASE_URL")
    if not dsn:
        return jsonify(message="Closure database is not configured."), 503
    try:
        if request.method == "POST":
            key = current_app.config.get("CLOSURE_CONFIRMATION_KEY")
            if not isinstance(key, str) or len(key.encode()) < 32:
                return jsonify(message="Closure confirmation is not configured."), 503
            return (
                jsonify(
                    closure_store.create(
                        dsn,
                        data,
                        str(UUID(request.headers["X-Dev-User-Id"])),
                        token,
                        key,
                    )
                ),
                201,
            )
        if closure_id is not None:
            closure = closure_store.read(dsn, closure_id=closure_id)
            if closure is None:
                return jsonify(message="Venue closure not found."), 404
            return jsonify(closure=closure)
        return jsonify(closure_store.read(dsn, venue=venue, limit=limit, after=after))
    except closure_store.PreviewChangedError:
        return (
            jsonify(
                message="Closure impact changed or confirmation expired. Refresh preview and confirm again.",
                code="CLOSURE_PREVIEW_CHANGED",
            ),
            409,
        )
    except psycopg2.IntegrityError as error:
        if error.pgcode == "23503":
            if error.diag.constraint_name == "VenueClosure_venue_id_fkey":
                return jsonify(message="Venue not found."), 404
            return jsonify(message="Creator does not exist."), 400
        return jsonify(message="Unable to save closure."), 503
    except psycopg2.Error:
        return jsonify(message="Unable to save or load closure."), 503

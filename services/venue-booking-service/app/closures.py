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
    from app import closure_clients

    try:
        data = create_input(request.get_json(silent=True))
    except (ValueError, OverflowError) as error:
        return jsonify(message=str(error)), 400
    headers = {
        "X-Dev-User-Id": str(UUID(request.headers["X-Dev-User-Id"])),
        "X-Dev-Role": "Venue Staff",
    }
    try:
        return jsonify(closure_clients.preview(data, headers))
    except closure_clients.ClosureUpstreamError as error:
        return jsonify(message="Unable to load complete closure impact."), error.status


@bp.route("/venue-closures", methods=["GET", "POST"])
@bp.get("/venue-closures/<closure_id>")
def closures(closure_id=None):
    from app.closure_contract import confirmation_input, uuid_value, list_input

    try:
        if request.method == "POST":
            data, token = confirmation_input(request.get_json(silent=True))
            data |= {"confirmed": True, "confirmationToken": token}
        elif closure_id is not None:
            closure_id = uuid_value(closure_id)
        else:
            venue, limit, after = list_input(request.args)
    except (ValueError, OverflowError) as error:
        return jsonify(message=str(error)), 400
    from app import closure_clients

    headers = {
        "X-Dev-User-Id": str(UUID(request.headers["X-Dev-User-Id"])),
        "X-Dev-Role": "Venue Staff",
    }
    try:
        if request.method == "POST":
            return jsonify(closure_clients.create(data, headers)), 201
        return jsonify(
            closure_clients.read(closure_id, request.args.to_dict(), headers)
        )
    except closure_clients.ClosureUpstreamError as error:
        if error.code == "CLOSURE_PREVIEW_CHANGED":
            return (
                jsonify(
                    code=error.code,
                    message="Closure impact changed or confirmation expired. Refresh preview and confirm again.",
                ),
                409,
            )
        return (
            jsonify(message="Closure dependency could not complete the request."),
            error.status,
        )

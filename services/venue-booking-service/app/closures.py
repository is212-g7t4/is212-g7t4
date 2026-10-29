"""SCRUM-170 closure routes, for signed-in Venue Staff."""

from flask import Blueprint, g, jsonify, request

bp = Blueprint("closures", __name__)


@bp.before_request
def staff_only():
    if request.method == "OPTIONS":
        return None
    if not g.user_id:
        return jsonify(message="Sign in to continue."), 401
    if g.role != "Venue Staff":
        return jsonify(message="Venue Staff role is required."), 403


@bp.post("/venue-closures/preview")
def preview():
    from app.closure_contract import create_input
    from app import closure_clients

    try:
        data = create_input(request.get_json(silent=True))
    except (ValueError, OverflowError) as error:
        return jsonify(message=str(error)), 400
    try:
        return jsonify(closure_clients.preview(data))
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

    try:
        if request.method == "POST":
            return jsonify(closure_clients.create(data)), 201
        return jsonify(closure_clients.read(closure_id, request.args.to_dict()))
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

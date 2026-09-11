from flask import Blueprint, jsonify

bp = Blueprint("template_atomic_service", __name__)


@bp.get("/health")
def health():
    return jsonify(status="ok")

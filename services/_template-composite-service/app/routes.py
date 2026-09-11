from flask import Blueprint, jsonify

bp = Blueprint("template_composite_service", __name__)


@bp.get("/health")
def health():
    return jsonify(status="ok")


# Placeholder for this composite's actual orchestration endpoint(s) — e.g.
# validate input, call one or more atomics via app/clients.py, log to Forum,
# publish to the broker, then respond. See docs/microservices-diagram-notes.md
# for the real numbered call sequence this composite should implement.

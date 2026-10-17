"""Own-inbox HTTP API. DEV identity is opt-in, not production authentication."""

import os
from uuid import UUID
from flask import Flask, request, jsonify
import psycopg2
from app import store


def create_app():
    app = Flask(__name__)
    app.config.update(
        DATABASE_URL=os.getenv("DATABASE_URL"),
        NOTIFICATION_DEV_MODE=os.getenv("NOTIFICATION_DEV_MODE") == "true",
        FRONTEND_ORIGIN=os.getenv("FRONTEND_ORIGIN", "http://localhost:5174"),
    )

    @app.after_request
    def cors(response):
        origin = request.headers.get("Origin")
        configured = app.config["FRONTEND_ORIGIN"]
        if origin in {
            configured,
            configured.replace("localhost", "127.0.0.1"),
            configured.replace("127.0.0.1", "localhost"),
        }:
            response.headers.update(
                {
                    "Access-Control-Allow-Origin": origin,
                    "Vary": "Origin",
                    "Access-Control-Allow-Headers": "Content-Type, X-Dev-User-Id, X-Dev-Role",
                    "Access-Control-Allow-Methods": "GET, PATCH, OPTIONS",
                }
            )
        return response

    @app.get("/health")
    def health():
        return jsonify(status="ok")

    @app.route("/notifications", methods=["GET"])
    @app.get("/notifications/unread-count")
    @app.patch("/notifications/<uuid:notification_id>")
    def inbox(notification_id=None):
        if not app.config["NOTIFICATION_DEV_MODE"]:
            return jsonify(message="Notification DEV mode is disabled."), 503
        try:
            user = str(UUID(request.headers.get("X-Dev-User-Id", "")))
            if not request.headers.get("X-Dev-Role"):
                raise ValueError()
        except ValueError:
            return jsonify(message="DEV identity is required."), 401
        if not app.config["DATABASE_URL"]:
            return jsonify(message="Notification database is not configured."), 503
        try:
            if notification_id:
                data = request.get_json(silent=True)
                if not isinstance(data, dict) or type(data.get("read")) is not bool:
                    raise ValueError("read must be boolean.")
                item = store.set_read(
                    app.config["DATABASE_URL"], user, str(notification_id), data["read"]
                )
                return (
                    (jsonify(notification=item), 200)
                    if item
                    else (jsonify(message="Notification not found."), 404)
                )
            if request.path.endswith("/unread-count"):
                return jsonify(
                    unreadCount=store.unread_count(app.config["DATABASE_URL"], user)
                )
            limit = int(request.args.get("limit", "20"))
            if not 1 <= limit <= 100 or request.args.get("unread", "false") not in {
                "true",
                "false",
            }:
                raise ValueError("Invalid pagination/filter.")
            after = store.decode_cursor(request.args.get("cursor"))
            return jsonify(
                store.list_inbox(
                    app.config["DATABASE_URL"],
                    user,
                    limit,
                    after,
                    request.args.get("unread") == "true",
                )
            )
        except (ValueError, TypeError):
            return jsonify(message="Invalid notification input."), 400
        except psycopg2.Error:
            return jsonify(message="Notification storage unavailable."), 503

    return app

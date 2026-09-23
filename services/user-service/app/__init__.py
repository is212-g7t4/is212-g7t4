import os
from uuid import UUID

import psycopg2
from dotenv import load_dotenv
from flask import Flask, jsonify, request

load_dotenv()

from app.models import UserNotFoundError, get_user, list_users


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
        configured_origin = app.config["FRONTEND_ORIGIN"]
        allowed_origins = {configured_origin}
        if configured_origin:
            allowed_origins.add(configured_origin.replace("localhost", "127.0.0.1"))
            allowed_origins.add(configured_origin.replace("127.0.0.1", "localhost"))
        if origin in allowed_origins:
            response.headers["Access-Control-Allow-Origin"] = origin
            response.headers["Vary"] = "Origin"
            response.headers["Access-Control-Allow-Headers"] = "Content-Type, Accept"
            response.headers["Access-Control-Allow-Methods"] = "GET, OPTIONS"
        if request.method == "OPTIONS":
            response.status_code = 200
        return response

    @app.errorhandler(psycopg2.Error)
    def database_failure(error):
        # Do not expose credentials, SQL or database internals in the response/log.
        return jsonify(
            message="Unable to load users. Please check the User Service database connection and schema."
        ), 503

    @app.get("/health")
    def health():
        return jsonify(status="ok")

    @app.get("/users")
    def users():
        role = request.args.get("role") or None
        if not app.config["DATABASE_URL"]:
            return jsonify(message="DATABASE_URL is not configured for User Service."), 503
        return jsonify(users=list_users(app.config["DATABASE_URL"], role))

    @app.get("/users/<uuid:user_id>")
    def user_details(user_id):
        if not app.config["DATABASE_URL"]:
            return jsonify(message="DATABASE_URL is not configured for User Service."), 503
        try:
            return jsonify(get_user(app.config["DATABASE_URL"], str(user_id))), 200
        except UserNotFoundError:
            return jsonify(message="User not found."), 404

    return app

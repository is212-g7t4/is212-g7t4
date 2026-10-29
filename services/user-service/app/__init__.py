import os
from uuid import UUID

import httpx
import psycopg2
from dotenv import load_dotenv
from flask import Flask, jsonify, request

load_dotenv()

from app.auth import authenticate
from app.models import UserNotFoundError, get_user, list_users


def create_app(config=None):
    app = Flask(__name__)
    app.config.from_mapping(
        DATABASE_URL=os.getenv("DATABASE_URL"),
        SUPABASE_URL=os.getenv("SUPABASE_URL"),
        SUPABASE_ANON_KEY=os.getenv("SUPABASE_ANON_KEY"),
        # The Vite dev server is pinned to 5174 (strictPort in
        # vite.config.ts), so that is the origin the browser sends.
        FRONTEND_ORIGIN=os.getenv("FRONTEND_ORIGIN", "http://localhost:5174"),
    )
    app.config.update(config or {})
    app.before_request(authenticate)

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
            response.headers["Access-Control-Allow-Headers"] = "Content-Type, Accept, Authorization"
            response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
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

    @app.post("/auth/login")
    def login():
        """SCRUM-8: exchange email + password for a Supabase access token and the caller's profile."""
        data = request.get_json(silent=True)
        email = data.get("email") if isinstance(data, dict) else None
        password = data.get("password") if isinstance(data, dict) else None
        if not isinstance(email, str) or not email.strip() or not isinstance(password, str) or not password:
            return jsonify(message="Email and password are required."), 400
        if not (app.config["SUPABASE_URL"] and app.config["SUPABASE_ANON_KEY"] and app.config["DATABASE_URL"]):
            return jsonify(message="Sign-in is not configured for User Service."), 503
        try:
            response = httpx.post(
                f"{app.config['SUPABASE_URL'].rstrip('/')}/auth/v1/token",
                params={"grant_type": "password"},
                json={"email": email.strip(), "password": password},
                headers={"apikey": app.config["SUPABASE_ANON_KEY"]},
                timeout=10,
            )
        except httpx.HTTPError:
            return jsonify(message="Unable to reach the sign-in service. Please try again."), 503
        # Supabase answers a wrong email or password with 400 invalid_credentials.
        if response.status_code in (400, 401):
            return jsonify(message="Incorrect email or password."), 401
        if not response.is_success:
            return jsonify(message="Unable to reach the sign-in service. Please try again."), 503
        session = response.json()
        try:
            user = get_user(app.config["DATABASE_URL"], session["user"]["id"])
        except UserNotFoundError:
            return jsonify(message="This account has no ConnectSphere profile."), 403
        return jsonify(accessToken=session["access_token"], expiresAt=session["expires_at"], user=user), 200

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

import os

from flask import Flask, request

from app.routes import bp


def create_app() -> Flask:
    app = Flask(__name__)
    app.config["FRONTEND_ORIGIN"] = os.getenv("FRONTEND_ORIGIN", "http://localhost:5174")

    @app.after_request
    def add_cors_headers(response):
        origin = request.headers.get("Origin")
        configured_origin = app.config["FRONTEND_ORIGIN"]
        allowed_origins = {configured_origin}
        if configured_origin:
            allowed_origins.add(configured_origin.replace("localhost", "127.0.0.1"))
            allowed_origins.add(configured_origin.replace("127.0.0.1", "localhost"))
        if origin in allowed_origins:
            response.headers["Access-Control-Allow-Origin"] = origin
            response.headers["Vary"] = "Origin"
            response.headers["Access-Control-Allow-Headers"] = "Content-Type"
            response.headers["Access-Control-Allow-Methods"] = "GET, POST, PATCH, OPTIONS"
        if request.method == "OPTIONS":
            response.status_code = 200
        return response

    app.register_blueprint(bp)
    return app

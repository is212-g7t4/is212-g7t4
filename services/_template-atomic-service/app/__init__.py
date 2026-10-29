from flask import Flask

from app.routes import bp
from app.auth import authenticate


def create_app() -> Flask:
    app = Flask(__name__)
    app.before_request(authenticate)
    app.register_blueprint(bp)
    return app

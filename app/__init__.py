from flask import Flask

from .auth.routes import auth
from .analytics.routes import analytics
from .core.routes import core

from .common.errors import register_error_handlers
from .common.logging import setup_logging

def create_app():
    app = Flask(__name__)

    # Register blueprints
    app.register_blueprint(auth)
    app.register_blueprint(analytics)
    app.register_blueprint(core)

    # Phase 1: logging & errors
    setup_logging(app)
    register_error_handlers(app)

    @app.route("/")
    def health_check():
        return "Api working!"

    return app

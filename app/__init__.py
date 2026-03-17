from flask import Flask
from flask_cors import CORS

from .extensions import db, migrate
from .config import Config

from .auth.routes import auth
from .analytics.routes import analytics_bp
from .core.routes import core
from .attendance.routes import attendance

from .common.errors import register_error_handlers
from .common.logging import setup_logging


def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)

    db.init_app(app)
    migrate.init_app(app, db)

    CORS(app, max_age=86400)

    # load models
    import app.models

    # register blueprints
    app.register_blueprint(auth)
    app.register_blueprint(analytics_bp)
    app.register_blueprint(core)
    app.register_blueprint(attendance)

    setup_logging(app)
    register_error_handlers(app)

    @app.route("/")
    def health_check():
        return {"status": "ok"}

    return app
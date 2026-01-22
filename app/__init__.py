from flask import Flask

from .extensions import db, migrate
from .config import Config

from .auth.routes import auth
from .analytics.routes import analytics
from .core.routes import core

from .common.errors import register_error_handlers
from .common.logging import setup_logging

def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)

    # init extensions
    db.init_app(app)
    migrate.init_app(app, db)

    # register blueprints
    app.register_blueprint(auth)
    app.register_blueprint(analytics)
    app.register_blueprint(core)

    # phase 1
    setup_logging(app)
    register_error_handlers(app)

    @app.route("/")
    def health_check():
        return "API working!"

    return app

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

    # init extensions
    db.init_app(app)
    migrate.init_app(app, db)


    CORS(app, max_age=86400)  # Cache preflight response for 24 hours


    #import models
    from app.models.product import Product
    from app.models.department import Department
    from app.models.user import User
    from app.models.contractor import Contractor
    from app.models.activity_log import ActivityLog
    from app.models.transaction import Transaction
    from app.models.supplier import Supplier
    from app.models.attendance import Attendance
    from app.models.categorysuborder import CategorySubOrder



    with app.app_context():
        from app import models

    # register blueprints
    app.register_blueprint(auth)
    app.register_blueprint(analytics_bp)
    app.register_blueprint(core)
    app.register_blueprint(attendance)

    # Logging and error handling
    setup_logging(app)
    register_error_handlers(app)

    @app.route("/")
    def health_check():
        return {'key': 'value'}

    return app
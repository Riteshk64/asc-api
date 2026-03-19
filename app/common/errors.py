from flask import jsonify, g, has_request_context
from sqlalchemy.exc import OperationalError


def register_error_handlers(app):
    @app.errorhandler(OperationalError)
    def db_operational_error(err):
        # Logged as 503 so clients can retry
        if has_request_context():
            app.logger.exception("db_operational_error")
        return jsonify({
            "success": False,
            "message": "Service temporarily unavailable. Please retry."
        }), 503

    @app.errorhandler(400)
    def bad_request(error):
        return jsonify({"success": False, "message": "Bad request"}), 400

    @app.errorhandler(401)
    def unauthorized(error):
        return jsonify({"success": False, "message": "Unauthorized"}), 401

    @app.errorhandler(403)
    def forbidden(error):
        return jsonify({"success": False, "message": "Forbidden"}), 403

    @app.errorhandler(404)
    def not_found(error):
        return jsonify({"success": False, "message": "Not found"}), 404

    @app.errorhandler(500)
    def server_error(error):
        # This captures stack trace in logs
        if has_request_context():
            app.logger.exception("unhandled_500")
        return jsonify({
            "success": False,
            "message": "Internal server error"
        }), 500

    @app.teardown_request
    def log_teardown_error(exc):
        if exc is not None and has_request_context():
            app.logger.exception("teardown_exception")
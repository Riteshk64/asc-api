import logging

def setup_logging(app):
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(levelname)s - %(message)s"
    )

    @app.before_request
    def log_request():
        app.logger.info("Request received")

    @app.after_request
    def log_response(response):
        app.logger.info(f"Response status: {response.status}")
        return response

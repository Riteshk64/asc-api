import logging
import time
import uuid
import json

from flask import g, request, has_request_context


class RequestContextFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        # Default fields so formatter never crashes
        record.request_id = "-"
        record.user_id = "-"
        record.role = "-"
        record.duration_ms = "-"
        record.method = "-"
        record.path = "-"
        record.status_code = "-"

        if has_request_context():
            record.request_id = getattr(g, "request_id", "-")
            record.user_id = getattr(getattr(g, "current_user", None), "id", "-")
            record.role = getattr(g, "role", "-")
            record.method = getattr(request, "method", "-")
            record.path = getattr(request, "path", "-")
            record.duration_ms = getattr(g, "request_duration_ms", "-")
            record.status_code = getattr(g, "response_status_code", "-")

        return True


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        log = {
            "ts": self.formatTime(record, self.datefmt),
            "level": record.levelname,
            "msg": record.getMessage(),
            "request_id": getattr(record, "request_id", "-"),
            "user_id": getattr(record, "user_id", "-"),
            "role": getattr(record, "role", "-"),
            "method": getattr(record, "method", "-"),
            "path": getattr(record, "path", "-"),
            "status_code": getattr(record, "status_code", "-"),
            "duration_ms": getattr(record, "duration_ms", "-"),
        }
        if record.exc_info:
            log["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(log, ensure_ascii=False)


def setup_logging(app):
    logger = app.logger
    logger.setLevel(logging.INFO)
    logger.propagate = False

    formatter = JsonFormatter()

    # Ensure at least one handler exists (writes to stdout)
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(formatter)
        logger.addHandler(handler)
    else:
        for handler in logger.handlers:
            handler.setFormatter(formatter)

    if not any(isinstance(f, RequestContextFilter) for f in logger.filters):
        logger.addFilter(RequestContextFilter())

    @app.before_request
    def start_request():
        # Light sampling: skip healthcheck logs if you want
        if request.path == "/":
            g.skip_logging = True
        else:
            g.skip_logging = False

        g.request_id = request.headers.get("X-Request-Id") or str(uuid.uuid4())
        g.request_start_time = time.perf_counter()
        g.request_duration_ms = "-"
        g.response_status_code = "-"

    @app.after_request
    def log_response(response):
        try:
            if hasattr(g, "request_start_time"):
                duration_ms = (time.perf_counter() - g.request_start_time) * 1000.0
                g.request_duration_ms = f"{duration_ms:.2f}"
            g.response_status_code = getattr(response, "status_code", "-")
            response.headers.setdefault("X-Request-Id", getattr(g, "request_id", "-"))

            if not getattr(g, "skip_logging", False):
                logger.info("request_complete")
        except Exception:
            # Never break responses because of logging
            pass

        return response
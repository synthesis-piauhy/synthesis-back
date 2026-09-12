import json
import logging
from time import monotonic
from uuid import UUID, uuid4


class JsonFormatter(logging.Formatter):
    fields = ("request_id", "method", "path", "status", "duration_ms", "report_id", "actor_id", "version")

    def format(self, record):
        payload = {
            "timestamp": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        payload.update({name: getattr(record, name) for name in self.fields if hasattr(record, name)})
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


class RequestLogMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response
        self.logger = logging.getLogger("synthesis.requests")

    def __call__(self, request):
        candidate = request.headers.get("X-Request-ID", "")
        try:
            request_id = str(UUID(candidate))
        except ValueError:
            request_id = str(uuid4())
        request.request_id = request_id
        started = monotonic()
        response = self.get_response(request)
        response["X-Request-ID"] = request_id
        self.logger.info(
            "request_completed",
            extra={
                "request_id": request_id,
                "method": request.method,
                "path": request.path,
                "status": response.status_code,
                "duration_ms": round((monotonic() - started) * 1000),
            },
        )
        return response

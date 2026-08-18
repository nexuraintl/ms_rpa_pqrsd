"""Logging estructurado JSON para Cloud Logging (GOB-GCP-STD-01).

Emite un objeto JSON por línea a stdout. Cloud Logging interpreta de forma
nativa los campos `severity`, `message` y `logging.googleapis.com/trace`, lo
que permite correlacionar los logs de un request con su traza en Cloud Trace.
"""

import datetime as _dt
import json
import logging
import sys
from typing import Any, Dict

from api.core.config import get_settings
from api.core.middleware import get_trace_context

# Atributos propios de LogRecord: todo lo demás que traiga el record se
# considera contexto de negocio y se serializa como campo del JSON.
# `color_message` lo inyecta uvicorn con secuencias ANSI: solo ensucia el log.
_RESERVED_ATTRS = frozenset(
    {
        "args", "asctime", "color_message", "created", "exc_info", "exc_text",
        "filename", "funcName", "levelname", "levelno", "lineno", "module",
        "msecs", "message", "msg", "name", "pathname", "process",
        "processName", "relativeCreated", "stack_info", "taskName", "thread",
        "threadName",
    }
)


class JsonFormatter(logging.Formatter):
    """Formatea cada LogRecord como una línea JSON compatible con Cloud Logging."""

    def format(self, record: logging.LogRecord) -> str:
        settings = get_settings()

        payload: Dict[str, Any] = {
            "severity": record.levelname,
            "message": record.getMessage(),
            "timestamp": _dt.datetime.fromtimestamp(
                record.created, tz=_dt.timezone.utc
            ).isoformat(),
            "logger": record.name,
            "service": settings.service_name,
            "version": settings.service_version,
            "environment": settings.environment,
        }

        ctx = get_trace_context()

        if ctx.get("correlation_id"):
            payload["correlation_id"] = ctx["correlation_id"]

        trace_id = ctx.get("trace_id")
        if trace_id and settings.google_cloud_project:
            payload["logging.googleapis.com/trace"] = (
                f"projects/{settings.google_cloud_project}/traces/{trace_id}"
            )
        elif trace_id:
            payload["trace_id"] = trace_id

        if ctx.get("span_id"):
            payload["logging.googleapis.com/spanId"] = ctx["span_id"]
        if ctx.get("trace_sampled") is not None:
            payload["logging.googleapis.com/trace_sampled"] = ctx["trace_sampled"]

        if record.exc_info:
            payload["stack_trace"] = self.formatException(record.exc_info)
        elif record.stack_info:
            payload["stack_trace"] = self.formatStack(record.stack_info)

        for key, value in record.__dict__.items():
            if key not in _RESERVED_ATTRS and not key.startswith("_"):
                payload[key] = value

        return json.dumps(payload, ensure_ascii=False, default=str)


def setup_logging(level: str | None = None) -> None:
    """Configura el logging JSON.

    Debe invocarse **antes** de instanciar FastAPI para que los loggers de
    uvicorn queden reencaminados al formatter JSON y no escriban texto plano.
    """
    settings = get_settings()
    resolved = (level or settings.log_level).upper()

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())

    root = logging.getLogger()
    for existing in list(root.handlers):
        root.removeHandler(existing)
    root.addHandler(handler)
    root.setLevel(resolved)

    # uvicorn instala sus propios handlers de texto plano: se vacían para que
    # sus registros se propaguen al root y salgan como JSON.
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access", "uvicorn.asgi"):
        uvicorn_logger = logging.getLogger(name)
        uvicorn_logger.handlers.clear()
        uvicorn_logger.propagate = True
        uvicorn_logger.setLevel(resolved)

    # httpx registra cada petición saliente en INFO; a DEBUG para no duplicar
    # el log de negocio que ya emite el servicio.
    logging.getLogger("httpx").setLevel("WARNING")
    logging.getLogger("httpcore").setLevel("WARNING")

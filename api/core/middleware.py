"""Correlation-ID y propagación de trace context (GOB-GCP-STD-01).

Cada request entrante recibe (o propaga) un `X-Correlation-ID` y, si viene
desde el load balancer de GCP o de un cliente W3C, se extrae el trace context
para que Cloud Logging correlacione logs y trazas.
"""

import logging
import re
import time
import uuid
from contextvars import ContextVar
from typing import Any, Dict, Optional

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

logger = logging.getLogger(__name__)

CORRELATION_ID_HEADER = "X-Correlation-ID"

_EMPTY_CONTEXT: Dict[str, Any] = {}

_trace_context: ContextVar[Dict[str, Any]] = ContextVar(
    "trace_context", default=_EMPTY_CONTEXT
)

# GCP: TRACE_ID/SPAN_ID;o=TRACE_TRUE
_CLOUD_TRACE_RE = re.compile(r"^(?P<trace>[0-9a-fA-F]+)(?:/(?P<span>\d+))?(?:;o=(?P<sampled>[01]))?")
# W3C: 00-<32 hex trace-id>-<16 hex span-id>-<2 hex flags>
_TRACEPARENT_RE = re.compile(
    r"^(?P<version>[0-9a-f]{2})-(?P<trace>[0-9a-f]{32})-(?P<span>[0-9a-f]{16})-(?P<flags>[0-9a-f]{2})$"
)


def get_trace_context() -> Dict[str, Any]:
    """Contexto de trazabilidad del request en curso. Lo consume el formatter."""
    return _trace_context.get()


def _parse_cloud_trace(header: str) -> Optional[Dict[str, Any]]:
    match = _CLOUD_TRACE_RE.match(header.strip())
    if not match:
        return None
    span = match.group("span")
    result: Dict[str, Any] = {"trace_id": match.group("trace")}
    if span:
        # Cloud Trace envía el span en decimal; Cloud Logging lo espera en hex.
        result["span_id"] = format(int(span), "016x")
    if match.group("sampled") is not None:
        result["trace_sampled"] = match.group("sampled") == "1"
    return result


def _parse_traceparent(header: str) -> Optional[Dict[str, Any]]:
    match = _TRACEPARENT_RE.match(header.strip().lower())
    if not match:
        return None
    return {
        "trace_id": match.group("trace"),
        "span_id": match.group("span"),
        "trace_sampled": bool(int(match.group("flags"), 16) & 0x01),
    }


def _extract_trace(request: Request) -> Dict[str, Any]:
    cloud_trace = request.headers.get("X-Cloud-Trace-Context")
    if cloud_trace:
        parsed = _parse_cloud_trace(cloud_trace)
        if parsed:
            return parsed

    traceparent = request.headers.get("traceparent")
    if traceparent:
        parsed = _parse_traceparent(traceparent)
        if parsed:
            return parsed

    return {}


class CorrelationMiddleware(BaseHTTPMiddleware):
    """Inyecta Correlation-ID, propaga trace context y registra cada request."""

    async def dispatch(self, request: Request, call_next) -> Response:
        correlation_id = request.headers.get(CORRELATION_ID_HEADER) or str(uuid.uuid4())

        context: Dict[str, Any] = {"correlation_id": correlation_id}
        context.update(_extract_trace(request))
        token = _trace_context.set(context)

        started = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            duration_ms = round((time.perf_counter() - started) * 1000, 2)
            logger.exception(
                "request_failed",
                extra={
                    "http_method": request.method,
                    "http_path": request.url.path,
                    "duration_ms": duration_ms,
                    "correlation_id": correlation_id,
                },
            )
            _trace_context.reset(token)
            raise

        duration_ms = round((time.perf_counter() - started) * 1000, 2)
        response.headers[CORRELATION_ID_HEADER] = correlation_id

        # Las sondas de Cloud Run golpean /health constantemente: se registran
        # en DEBUG para no inundar Cloud Logging.
        if response.status_code >= 500:
            level = logging.ERROR
        elif response.status_code >= 400:
            level = logging.WARNING
        elif request.url.path in ("/health", "/version"):
            level = logging.DEBUG
        else:
            level = logging.INFO

        logger.log(
            level,
            "request_completed",
            extra={
                "http_method": request.method,
                "http_path": request.url.path,
                "http_status": response.status_code,
                "duration_ms": duration_ms,
                "correlation_id": correlation_id,
            },
        )

        _trace_context.reset(token)
        return response

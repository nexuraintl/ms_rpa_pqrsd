"""Endpoints de infraestructura y Correlation-ID (GOB-GCP-STD-01)."""

import json
import logging

from api.core.logging import JsonFormatter
from api.core.middleware import CORRELATION_ID_HEADER


def test_health_ok(plain_client):
    response = plain_client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "UP"}


def test_version_ok(plain_client):
    response = plain_client.get("/version")
    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"service", "version", "environment"}
    assert body["environment"] == "test"


def test_correlation_id_header(plain_client):
    response = plain_client.get("/health")
    assert response.headers.get(CORRELATION_ID_HEADER)


def test_correlation_id_propagated(plain_client):
    enviado = "11111111-2222-3333-4444-555555555555"
    response = plain_client.get("/health", headers={CORRELATION_ID_HEADER: enviado})
    assert response.headers[CORRELATION_ID_HEADER] == enviado


def test_health_sin_prefijo_de_version(plain_client):
    """Los endpoints de infraestructura no viven bajo /v1."""
    assert plain_client.get("/v1/health").status_code == 404


def test_logs_en_json_con_severity():
    record = logging.LogRecord(
        name="test", level=logging.WARNING, pathname=__file__, lineno=1,
        msg="mensaje de prueba", args=(), exc_info=None,
    )
    salida = json.loads(JsonFormatter().format(record))

    assert salida["severity"] == "WARNING"
    assert salida["message"] == "mensaje de prueba"
    assert "timestamp" in salida
    assert "level" not in salida and "levelname" not in salida


def test_log_incluye_trace_y_correlation_id():
    from api.core.middleware import _trace_context

    token = _trace_context.set(
        {"correlation_id": "abc-123", "trace_id": "0af7651916cd43dd8448eb211c80319c"}
    )
    try:
        record = logging.LogRecord(
            name="test", level=logging.INFO, pathname=__file__, lineno=1,
            msg="con trace", args=(), exc_info=None,
        )
        salida = json.loads(JsonFormatter().format(record))
    finally:
        _trace_context.reset(token)

    assert salida["correlation_id"] == "abc-123"
    assert salida["logging.googleapis.com/trace"] == (
        "projects/proyecto-de-prueba/traces/0af7651916cd43dd8448eb211c80319c"
    )

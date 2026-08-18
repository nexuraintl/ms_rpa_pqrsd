# syntax=docker/dockerfile:1

# ---------- Etapa de construcción ----------
FROM python:3.12-slim AS builder

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

WORKDIR /build
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt


# ---------- Imagen final ----------
FROM python:3.12-slim AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/opt/venv/bin:$PATH"

# Usuario sin privilegios (GOB-GCP-STD-01: nunca ejecutar como root).
RUN useradd --create-home --uid 10001 appuser

COPY --from=builder /opt/venv /opt/venv

WORKDIR /app
COPY --chown=appuser:appuser api ./api

USER appuser

EXPOSE 8080

# Cloud Run inyecta $PORT; el valor por defecto solo aplica en ejecución local.
# Un único worker: la app es asíncrona y Cloud Run escala por instancias.
# El keep-alive supera el idle timeout del balanceador (600 s) para evitar
# 502 por reutilización de una conexión que el servidor acaba de cerrar.
CMD exec uvicorn api.main:app \
    --host 0.0.0.0 \
    --port ${PORT:-8080} \
    --workers 1 \
    --timeout-keep-alive 620 \
    --no-server-header

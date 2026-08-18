"""Punto de entrada del microservicio (GOB-GCP-STD-01).

Este módulo solo hace setup y registro: la lógica de negocio vive en
`api/routers/v1/` y `api/services/`.
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from api.core.config import get_settings
from api.core.logging import setup_logging
from api.core.middleware import (
    CORRELATION_ID_HEADER,
    CorrelationMiddleware,
    get_trace_context,
)
from api.routers import health
from api.routers.v1 import pqrsd

# Debe ejecutarse antes de instanciar FastAPI para que los handlers de uvicorn
# queden reencaminados al formatter JSON.
setup_logging()

logger = logging.getLogger(__name__)
settings = get_settings()


@asynccontextmanager
async def lifespan(_: FastAPI):
    logger.info(
        "service_started",
        extra={
            "environment": settings.environment,
            "log_level": settings.log_level,
            "portal_consulta_url": settings.portal_consulta_url,
        },
    )
    yield
    logger.info("service_stopped")


app = FastAPI(
    title=settings.service_name,
    version=settings.service_version,
    description=settings.project_description,
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
    lifespan=lifespan,
)

app.add_middleware(CorrelationMiddleware)

# Detrás del API Gateway no hay tráfico de navegador y CORS queda deshabilitado.
# Para exponer el servicio directo a un frontend, definir CORS_ALLOW_ORIGINS.
_origins = settings.cors_origins_list
if _origins:
    comodin = "*" in _origins
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_origins,
        # Los navegadores rechazan `Access-Control-Allow-Origin: *` junto con
        # credenciales, por lo que ambas opciones son excluyentes.
        allow_credentials=not comodin,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["*"],
        expose_headers=[CORRELATION_ID_HEADER],
    )

app.include_router(health.router)
app.include_router(pqrsd.router)


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Evita filtrar trazas al cliente; el detalle queda en Cloud Logging."""
    correlation_id = get_trace_context().get("correlation_id")
    logger.exception(
        "unhandled_exception",
        extra={"http_path": request.url.path, "correlation_id": correlation_id},
    )
    return JSONResponse(
        status_code=500,
        content={
            "detail": "Error interno del microservicio.",
            "correlation_id": correlation_id,
        },
        headers={CORRELATION_ID_HEADER: correlation_id} if correlation_id else None,
    )

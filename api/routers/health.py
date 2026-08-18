"""Endpoints de infraestructura: sin prefijo de versión y sin autenticación.

Cloud Run los usa como startup/liveness probe y el API Gateway los deja fuera
del bloque `security` (GOB-GCP-STD-01).
"""

from fastapi import APIRouter

from api.core.config import get_settings
from api.models.schemas import HealthResponse, VersionResponse

router = APIRouter(tags=["infra"])


@router.get("/health", response_model=HealthResponse, operation_id="getHealth")
async def health() -> dict:
    return {"status": "UP"}


@router.get("/version", response_model=VersionResponse, operation_id="getVersion")
async def version() -> dict:
    settings = get_settings()
    return {
        "service": settings.service_name,
        "version": settings.service_version,
        "environment": settings.environment,
    }

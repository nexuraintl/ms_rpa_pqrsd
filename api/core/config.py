"""Configuración del microservicio (GOB-GCP-STD-01).

Toda la configuración se resuelve desde variables de entorno. Los secretos se
inyectan desde Secret Manager por Cloud Run; nunca se declaran valores reales
en el código ni en `.env.example`.
"""

from functools import lru_cache
from typing import List

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # --- Variables base exigidas por el estándar ---
    service_name: str = "ms-rpa-pqrsd"
    service_version: str = "1.0.0"
    environment: str = "dev"
    log_level: str = "INFO"
    google_cloud_project: str = ""

    # --- Metadatos expuestos en OpenAPI ---
    project_description: str = (
        "Microservicio RPA para consulta y radicación de PQRSD en el "
        "Portal Suite Neptuno de la Alcaldía de Floridablanca."
    )

    # --- Portal externo (Suite Neptuno) ---
    portal_consulta_url: str = (
        "https://portal.floridablanca.suiteneptuno.com/Correspondencia/Consulta/Consulta"
    )
    portal_radicacion_url: str = (
        "https://portal.floridablanca.suiteneptuno.com/Correspondencia/Radicacion/Radicacion"
    )
    portal_user_agent: str = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    )

    # --- Cliente HTTP saliente ---
    http_timeout_seconds: float = 30.0
    http_connect_timeout_seconds: float = 10.0
    http_max_retries: int = 2
    http_max_connections: int = 20
    http_max_keepalive_connections: int = 10

    # Los catálogos del portal cambian con muy baja frecuencia. Cachearlos en
    # memoria evita 7 peticiones al portal público en cada request entrante.
    catalogos_cache_ttl_seconds: int = 300

    # --- Límites de carga de archivos ---
    max_upload_files: int = 10
    max_upload_bytes: int = 10 * 1024 * 1024  # 10 MB por archivo
    max_upload_total_bytes: int = 25 * 1024 * 1024  # 25 MB en total

    # --- CORS ---
    # Lista separada por comas. Vacío = sin CORS (caso API Gateway).
    cors_allow_origins: str = ""

    # --- Diagnóstico ---
    # Devuelve el payload crudo del portal en la respuesta de /v1/pqrsd/crear.
    # Debe permanecer en False fuera de dev: expone datos del ciudadano.
    expose_raw_response: bool = False

    @property
    def cors_origins_list(self) -> List[str]:
        return [o.strip() for o in self.cors_allow_origins.split(",") if o.strip()]

    @property
    def is_production(self) -> bool:
        return self.environment.lower() in {"prod", "production", "prem", "preprod"}


@lru_cache
def get_settings() -> Settings:
    """Instancia única de Settings; evita re-leer el entorno en cada request."""
    return Settings()

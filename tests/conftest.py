"""Fixtures compartidas.

Ningún test toca el portal real: todas las respuestas del Portal Suite Neptuno
se simulan con `httpx.MockTransport`. Un test que dependa de la red haría
fallar el build en Cloud Build.
"""

import os

# Debe fijarse antes de importar la app: Settings se cachea con @lru_cache.
os.environ.setdefault("ENVIRONMENT", "test")
os.environ.setdefault("LOG_LEVEL", "WARNING")
os.environ.setdefault("GOOGLE_CLOUD_PROJECT", "proyecto-de-prueba")
os.environ.setdefault("CATALOGOS_CACHE_TTL_SECONDS", "0")
os.environ.setdefault("HTTP_MAX_RETRIES", "0")

import httpx  # noqa: E402
import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from api.core.config import get_settings  # noqa: E402
from api.main import app  # noqa: E402
from api.services.pqrsd_service import PQRSDRPAService, get_pqrsd_service  # noqa: E402

TOKEN_HTML = (
    '<html><body><form>'
    '<input name="__RequestVerificationToken" type="hidden" value="TOKEN-DE-PRUEBA" />'
    '</form></body></html>'
)

CORRESPONDENCIA = {
    "Correspondencia": {
        "Id": 488450,
        "Radicado": "2026488450",
        "EstadoCorrespondencia": {"Estado": "En revisión"},
        "TipoCorrespondencia": {"Nombre": "Petición"},
        "FechaRadiacion": "2026-07-29T07:10:00",
        "MetodoRecepcion": "Portal web",
        "Remitente": {"NombreConcatenado": "ANÓNIMO", "Email": "sincorreo@gmail.com"},
        "Asunto": "Prueba automatizada",
        "Respuesta": None,
    }
}

RADICADO_GENERADO = {
    "Item1": {
        "Correspondencia": {
            "Id": 488452,
            "Radicado": "2026488452",
            "CodigoAutenticacion": "2025jRhhE22026488452",
            "FechaRadiacion": "2026-07-29T07:10:00",
        }
    }
}


def portal_handler(request: httpx.Request) -> httpx.Response:
    """Simula el portal Neptuno para el camino feliz."""
    handler = request.url.params.get("handler")
    path = request.url.path

    if request.method == "GET" and handler is None:
        return httpx.Response(200, text=TOKEN_HTML)

    if handler == "BuscarCorrespondencia":
        contenido = request.content.decode()
        if "0000000000" in contenido:
            return httpx.Response(200, json={"Correspondencia": None})
        return httpx.Response(200, json=CORRESPONDENCIA)

    if handler == "ListaAnexos":
        return httpx.Response(200, json={"data": [{"NombreArchivo": "soporte.pdf"}]})

    if handler == "FlujoCorrespondencia":
        return httpx.Response(200, json=[{"FechaAsignacionString": "29/07/26 7:10 a. m."}])

    if handler == "GenerarRadicado":
        return httpx.Response(200, json=RADICADO_GENERADO)

    if handler and handler.startswith("Lista"):
        return httpx.Response(200, json={"data": [{"Id": 6, "Nombre": "Petición"}]})

    return httpx.Response(404, text=f"handler no simulado: {handler} ({path})")


def build_client(handler) -> TestClient:
    """TestClient con el servicio apuntando a un portal simulado."""
    service = PQRSDRPAService(
        settings=get_settings(), transport=httpx.MockTransport(handler)
    )
    app.dependency_overrides[get_pqrsd_service] = lambda: service
    return TestClient(app)


@pytest.fixture
def client():
    with build_client(portal_handler) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture
def plain_client():
    """Cliente sin override: sirve para /health y /version, que no salen a red."""
    with TestClient(app) as c:
        yield c

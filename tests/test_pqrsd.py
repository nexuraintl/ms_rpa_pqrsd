"""Endpoints de negocio bajo /v1, contra un portal Neptuno simulado."""

import httpx
import pytest

from api.core.config import Settings, get_settings
from api.main import app
from api.services.pqrsd_service import _extraer_token
from tests.conftest import TOKEN_HTML, build_client, portal_handler


# --------------------------------------------------------------------------- #
# Catálogos
# --------------------------------------------------------------------------- #

def test_catalogos_ok(client):
    response = client.get("/v1/pqrsd/catalogos")
    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert body["tipos_correspondencia"] == [{"Id": 6, "Nombre": "Petición"}]
    assert body["dependencias_areas"]


def test_catalogos_portal_caido():
    def caido(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, text="portal en mantenimiento")

    with build_client(caido) as c:
        body = c.get("/v1/pqrsd/catalogos").json()

    assert body["success"] is False
    assert "503" in body["message"]
    assert body["tipos_correspondencia"] == []
    app.dependency_overrides.clear()


def test_catalogos_reporta_faltantes_sin_fallar():
    """Un catálogo caído degrada la respuesta, no la invalida."""

    def parcial(request: httpx.Request) -> httpx.Response:
        handler = request.url.params.get("handler")
        if handler is None:
            return httpx.Response(200, text=TOKEN_HTML)
        if handler == "ListaArea":
            return httpx.Response(500)
        return httpx.Response(200, json={"data": [{"Id": 6, "Nombre": "Petición"}]})

    with build_client(parcial) as c:
        body = c.get("/v1/pqrsd/catalogos").json()

    assert body["success"] is True
    assert body["dependencias_areas"] == []
    assert "dependencias_areas" in body["message"]
    app.dependency_overrides.clear()


# --------------------------------------------------------------------------- #
# Consulta
# --------------------------------------------------------------------------- #

def test_consultar_encontrado(client):
    response = client.post(
        "/v1/pqrsd/consultar",
        json={"radicado": "2026488450", "codigo_autenticacion": "202UhXbRIu2026488450"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert body["found"] is True
    assert body["datos_correspondencia"]["estado"] == "En revisión"
    assert body["anexos"] == [{"NombreArchivo": "soporte.pdf"}]
    assert len(body["flujo"]) == 1


def test_consultar_no_encontrado(client):
    response = client.post(
        "/v1/pqrsd/consultar",
        json={"radicado": "0000000000", "codigo_autenticacion": "0000"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert body["found"] is False
    assert "No se encontró" in body["message"]


def test_consultar_portal_caido_devuelve_502():
    def caido(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500)

    with build_client(caido) as c:
        response = c.post(
            "/v1/pqrsd/consultar",
            json={"radicado": "2026488450", "codigo_autenticacion": "x"},
        )

    assert response.status_code == 502
    app.dependency_overrides.clear()


def test_consultar_valida_campos_vacios(client):
    response = client.post(
        "/v1/pqrsd/consultar", json={"radicado": "", "codigo_autenticacion": ""}
    )
    assert response.status_code == 422


# --------------------------------------------------------------------------- #
# Radicación
# --------------------------------------------------------------------------- #

def test_crear_ok(client):
    response = client.post(
        "/v1/pqrsd/crear",
        data={
            "asunto": "Petición sobre estado de vía pública",
            "email": "ciudadano@example.com",
            "telefono_celular": "3109876543",
            "es_anonimo": "true",
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert body["radicado"] == "2026488452"
    assert body["codigo_autenticacion"] == "2025jRhhE22026488452"


def test_crear_con_anexo(client):
    response = client.post(
        "/v1/pqrsd/crear",
        data={
            "asunto": "Con soporte adjunto",
            "email": "ciudadano@example.com",
            "telefono_celular": "3109876543",
        },
        files=[("archivos", ("soporte.pdf", b"%PDF-1.4 contenido", "application/pdf"))],
    )
    assert response.status_code == 200
    assert response.json()["radicado"] == "2026488452"


def test_crear_no_expone_raw_response(client):
    """El payload crudo trae datos del ciudadano: oculto salvo EXPOSE_RAW_RESPONSE."""
    response = client.post(
        "/v1/pqrsd/crear",
        data={
            "asunto": "Sin raw",
            "email": "ciudadano@example.com",
            "telefono_celular": "3109876543",
        },
    )
    assert response.json()["raw_response"] is None


def test_crear_identificado_exige_documento(client):
    response = client.post(
        "/v1/pqrsd/crear",
        data={
            "asunto": "Radicación identificada",
            "email": "ciudadano@example.com",
            "telefono_celular": "3109876543",
            "es_anonimo": "false",
        },
    )
    assert response.status_code == 422
    assert "numero_identificacion" in response.json()["detail"]


def test_crear_rechaza_demasiados_archivos(client):
    app.dependency_overrides[get_settings] = lambda: Settings(max_upload_files=2)
    response = client.post(
        "/v1/pqrsd/crear",
        data={
            "asunto": "Muchos anexos",
            "email": "ciudadano@example.com",
            "telefono_celular": "3109876543",
        },
        files=[
            ("archivos", (f"anexo{i}.txt", b"contenido", "text/plain")) for i in range(3)
        ],
    )
    assert response.status_code == 413
    assert "Máximo 2 archivos" in response.json()["detail"]


def test_crear_rechaza_archivo_grande(client):
    app.dependency_overrides[get_settings] = lambda: Settings(max_upload_bytes=1024)
    response = client.post(
        "/v1/pqrsd/crear",
        data={
            "asunto": "Anexo pesado",
            "email": "ciudadano@example.com",
            "telefono_celular": "3109876543",
        },
        files=[("archivos", ("grande.bin", b"x" * 5000, "application/octet-stream"))],
    )
    assert response.status_code == 413
    assert "grande.bin" in response.json()["detail"]


def test_crear_rechaza_total_excedido(client):
    app.dependency_overrides[get_settings] = lambda: Settings(
        max_upload_bytes=4096, max_upload_total_bytes=5000
    )
    response = client.post(
        "/v1/pqrsd/crear",
        data={
            "asunto": "Suma excedida",
            "email": "ciudadano@example.com",
            "telefono_celular": "3109876543",
        },
        files=[
            ("archivos", ("a.bin", b"x" * 3000, "application/octet-stream")),
            ("archivos", ("b.bin", b"x" * 3000, "application/octet-stream")),
        ],
    )
    assert response.status_code == 413
    assert "tamaño total" in response.json()["detail"]


# --------------------------------------------------------------------------- #
# Estructura y utilidades
# --------------------------------------------------------------------------- #

def test_negocio_esta_bajo_v1(client):
    """La ruta legada /api/v1 ya no existe (GOB-GCP-STD-01)."""
    assert client.get("/api/v1/pqrsd/catalogos").status_code == 404


@pytest.mark.parametrize(
    "html",
    [
        '<input name="__RequestVerificationToken" type="hidden" value="ABC123" />',
        '<input type="hidden" value="ABC123" name="__RequestVerificationToken">',
        "<input value='ABC123' name='__RequestVerificationToken' type='hidden'>",
    ],
)
def test_extraer_token_tolera_orden_de_atributos(html):
    """El portal emite los atributos en distinto orden según la vista."""
    assert _extraer_token(html) == "ABC123"


def test_extraer_token_sin_input():
    assert _extraer_token("<html><body>sin formulario</body></html>") is None


def test_radicacion_no_se_reintenta():
    """Reintentar GenerarRadicado crearía un segundo radicado real."""
    intentos = {"generar": 0}

    def contando(request: httpx.Request) -> httpx.Response:
        handler = request.url.params.get("handler")
        if handler is None:
            return httpx.Response(200, text=TOKEN_HTML)
        if handler == "GenerarRadicado":
            intentos["generar"] += 1
            return httpx.Response(500)
        return portal_handler(request)

    with build_client(contando) as c:
        response = c.post(
            "/v1/pqrsd/crear",
            data={
                "asunto": "Fallo del portal",
                "email": "ciudadano@example.com",
                "telefono_celular": "3109876543",
            },
        )

    assert response.status_code == 502
    assert intentos["generar"] == 1
    app.dependency_overrides.clear()

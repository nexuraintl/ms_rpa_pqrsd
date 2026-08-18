"""Servicio RPA contra el Portal Suite Neptuno (Alcaldía de Floridablanca).

Todo el I/O es asíncrono (`httpx.AsyncClient`): el servicio se invoca desde
handlers `async def`, por lo que una implementación bloqueante dejaría el event
loop congelado y anularía la concurrencia del contenedor en Cloud Run.
"""

import asyncio
import json
import logging
import re
import time
from typing import Any, Dict, List, Optional, Tuple

import httpx

from api.core.config import Settings, get_settings

logger = logging.getLogger(__name__)

# El portal renderiza el input del token con los atributos en distinto orden
# según la vista; se localiza el <input> por su name y luego se lee el value.
_TOKEN_INPUT_RE = re.compile(
    r"<input[^>]*name=[\"']__RequestVerificationToken[\"'][^>]*>", re.IGNORECASE
)
_VALUE_ATTR_RE = re.compile(r"value=[\"']([^\"']+)[\"']", re.IGNORECASE)

_CATALOGO_HANDLERS = {
    "tipos_correspondencia": "ListaTipoCorrespondencia",
    "dependencias_areas": "ListaArea",
    "condiciones_discapacidad": "ListaCondicionDiscapacidad",
    "grupos_etnicos": "ListaGrupoEtnico",
    "grupos_interes": "ListaGrupoInteres",
    "atencion_preferencial": "ListaAtencionPreferencial",
    "medios_respuesta": "ListaMedioRespuesta",
}


class PortalUnavailableError(RuntimeError):
    """El portal Neptuno no respondió o respondió algo no interpretable."""


def _extraer_token(html: str) -> Optional[str]:
    tag = _TOKEN_INPUT_RE.search(html)
    if not tag:
        return None
    value = _VALUE_ATTR_RE.search(tag.group(0))
    return value.group(1) if value else None


def _unwrap_data(payload: Any) -> List[Dict[str, Any]]:
    """El portal devuelve unas veces `{"data": [...]}` y otras la lista pelada."""
    if isinstance(payload, dict):
        data = payload.get("data")
        return data if isinstance(data, list) else []
    if isinstance(payload, list):
        return payload
    return []


class PQRSDRPAService:
    """Consulta, catálogos y radicación de PQRSD en Suite Neptuno."""

    def __init__(
        self,
        settings: Optional[Settings] = None,
        transport: Optional[httpx.AsyncBaseTransport] = None,
    ) -> None:
        self._settings = settings or get_settings()
        # Inyectable para poder ejercitar el servicio en tests sin red real.
        self._transport = transport
        self._catalogos_cache: Optional[Dict[str, Any]] = None
        self._catalogos_cached_at: float = 0.0
        self._catalogos_lock = asyncio.Lock()

    # ------------------------------------------------------------------ #
    # Infraestructura HTTP
    # ------------------------------------------------------------------ #

    def _client(self) -> httpx.AsyncClient:
        s = self._settings
        return httpx.AsyncClient(
            transport=self._transport,
            timeout=httpx.Timeout(
                s.http_timeout_seconds, connect=s.http_connect_timeout_seconds
            ),
            limits=httpx.Limits(
                max_connections=s.http_max_connections,
                max_keepalive_connections=s.http_max_keepalive_connections,
            ),
            headers={
                "User-Agent": s.portal_user_agent,
                "X-Requested-With": "XMLHttpRequest",
            },
            follow_redirects=True,
        )

    async def _get_with_retry(
        self, client: httpx.AsyncClient, url: str, **kwargs: Any
    ) -> httpx.Response:
        """GET con reintentos.

        Solo se reintentan peticiones idempotentes. La radicación (POST a
        `GenerarRadicado`) nunca se reintenta: un reenvío crearía un segundo
        radicado real en el portal de la Alcaldía.
        """
        attempts = max(1, self._settings.http_max_retries + 1)
        last_exc: Optional[Exception] = None

        for attempt in range(attempts):
            try:
                response = await client.get(url, **kwargs)
                if response.status_code >= 500 and attempt < attempts - 1:
                    logger.warning(
                        "portal_reintento",
                        extra={"url": url, "status": response.status_code,
                               "attempt": attempt + 1},
                    )
                    await asyncio.sleep(0.5 * (2**attempt))
                    continue
                return response
            except httpx.HTTPError as exc:
                last_exc = exc
                if attempt < attempts - 1:
                    logger.warning(
                        "portal_reintento",
                        extra={"url": url, "error": str(exc), "attempt": attempt + 1},
                    )
                    await asyncio.sleep(0.5 * (2**attempt))
                    continue

        raise PortalUnavailableError(
            f"El portal Neptuno no respondió tras {attempts} intentos: {last_exc}"
        )

    async def _cargar_token(self, client: httpx.AsyncClient, url: str) -> Tuple[str, httpx.Response]:
        response = await self._get_with_retry(client, url)
        if response.status_code != 200:
            raise PortalUnavailableError(
                f"No se pudo cargar la página del portal. HTTP {response.status_code}"
            )
        token = _extraer_token(response.text)
        if not token:
            raise PortalUnavailableError(
                "No se pudo extraer el token de verificación CSRF del portal"
            )
        return token, response

    # ------------------------------------------------------------------ #
    # Consulta de radicado
    # ------------------------------------------------------------------ #

    async def consultar(self, radicado: str, codigo_autenticacion: str) -> Dict[str, Any]:
        url = self._settings.portal_consulta_url

        async with self._client() as client:
            try:
                token, _ = await self._cargar_token(client, url)
            except PortalUnavailableError as exc:
                logger.error("consulta_token_fallida", extra={"error": str(exc)})
                return {"success": False, "found": False, "message": str(exc)}

            payload = {
                "correspodencia[Radicado]": radicado,
                "correspodencia[CodigoAutenticacion]": codigo_autenticacion,
                "__RequestVerificationToken": token,
            }

            try:
                resp = await client.post(f"{url}?handler=BuscarCorrespondencia", data=payload)
            except httpx.HTTPError as exc:
                logger.error("consulta_fallida", extra={"error": str(exc)})
                return {
                    "success": False,
                    "found": False,
                    "message": f"Error de comunicación con el portal Neptuno: {exc}",
                }

            if resp.status_code != 200:
                return {
                    "success": False,
                    "found": False,
                    "message": (
                        "Respuesta inesperada al consultar correspondencia: "
                        f"HTTP {resp.status_code}"
                    ),
                }

            try:
                data_buscar = resp.json()
            except ValueError:
                return {
                    "success": False,
                    "found": False,
                    "message": "El portal Neptuno devolvió una respuesta no interpretable",
                }

            correspondencia = data_buscar.get("Correspondencia")
            if not correspondencia:
                return {
                    "success": True,
                    "found": False,
                    "message": (
                        "No se encontró un registro con los datos ingresados. "
                        "Verifique Radicado y Código."
                    ),
                }

            radicado_id = correspondencia.get("Id")
            # `handler` viaja dentro de params: httpx **reemplaza** el query
            # string de la URL cuando se pasa `params=`, en vez de fusionarlo
            # como hacía requests.
            params = {
                "radicado": radicado,
                "radicadoId": radicado_id,
                "__RequestVerificationToken": token,
            }

            # Anexos y flujo son independientes entre sí: se piden en paralelo.
            anexos, flujo = await asyncio.gather(
                self._listar_seccion(client, url, "ListaAnexos", params),
                self._listar_seccion(client, url, "FlujoCorrespondencia", params),
            )

            remitente = correspondencia.get("Remitente") or {}
            estado = correspondencia.get("EstadoCorrespondencia") or {}
            tipo = correspondencia.get("TipoCorrespondencia") or {}

            logger.info(
                "consulta_exitosa",
                extra={"radicado": radicado, "radicado_id": radicado_id},
            )

            return {
                "success": True,
                "found": True,
                "message": "Consulta realizada exitosamente",
                "datos_correspondencia": {
                    "id": correspondencia.get("Id"),
                    "radicado": correspondencia.get("Radicado"),
                    "estado": estado.get("Estado"),
                    "tipo_correspondencia": tipo.get("Nombre"),
                    "fecha_radicacion": correspondencia.get("FechaRadiacion"),
                    "metodo_recepcion": correspondencia.get("MetodoRecepcion"),
                    "remitente": remitente.get("NombreConcatenado"),
                    "email": remitente.get("Email"),
                    "asunto": correspondencia.get("Asunto"),
                    "respuesta": correspondencia.get("Respuesta"),
                },
                "anexos": anexos,
                "flujo": flujo,
            }

    async def _listar_seccion(
        self,
        client: httpx.AsyncClient,
        url: str,
        handler: str,
        params: Dict[str, Any],
    ) -> List[Dict[str, Any]]:
        """Secciones accesorias: un fallo aquí degrada, no invalida la consulta."""
        try:
            resp = await self._get_with_retry(
                client, url, params={"handler": handler, **params}
            )
            if resp.status_code != 200:
                return []
            return _unwrap_data(resp.json())
        except (PortalUnavailableError, httpx.HTTPError, ValueError) as exc:
            logger.warning("seccion_no_disponible", extra={"handler": handler, "error": str(exc)})
            return []

    # ------------------------------------------------------------------ #
    # Catálogos
    # ------------------------------------------------------------------ #

    async def obtener_catalogos(self, forzar_refresco: bool = False) -> Dict[str, Any]:
        ttl = self._settings.catalogos_cache_ttl_seconds

        if not forzar_refresco and self._catalogos_cache is not None:
            if (time.monotonic() - self._catalogos_cached_at) < ttl:
                return self._catalogos_cache

        async with self._catalogos_lock:
            # Otra corrutina pudo refrescar el caché mientras se esperaba el lock.
            if not forzar_refresco and self._catalogos_cache is not None:
                if (time.monotonic() - self._catalogos_cached_at) < ttl:
                    return self._catalogos_cache

            resultado = await self._descargar_catalogos()

            if resultado["success"]:
                self._catalogos_cache = resultado
                self._catalogos_cached_at = time.monotonic()
            elif self._catalogos_cache is not None:
                # El portal falló pero hay una copia previa: se sirve marcada
                # como obsoleta en vez de devolver listas vacías.
                obsoleto = dict(self._catalogos_cache)
                obsoleto["message"] = (
                    "El portal Neptuno no respondió; se devuelven catálogos "
                    "de la última consulta exitosa."
                )
                return obsoleto

            return resultado

    async def _descargar_catalogos(self) -> Dict[str, Any]:
        url = self._settings.portal_radicacion_url
        resultado: Dict[str, Any] = {"success": True, "message": None}

        async with self._client() as client:
            try:
                # Establece la sesión/cookies antes de pedir los handlers.
                inicial = await self._get_with_retry(client, url)
                if inicial.status_code != 200:
                    raise PortalUnavailableError(
                        "No se pudo cargar la página de radicación del portal. "
                        f"HTTP {inicial.status_code}"
                    )
            except PortalUnavailableError as exc:
                logger.error("catalogos_portal_inaccesible", extra={"error": str(exc)})
                return {
                    "success": False,
                    "message": str(exc),
                    **{clave: [] for clave in _CATALOGO_HANDLERS},
                }

            async def _pedir(clave: str, handler: str) -> Tuple[str, List[Dict[str, Any]]]:
                try:
                    resp = await self._get_with_retry(client, f"{url}?handler={handler}")
                    if resp.status_code != 200:
                        logger.warning(
                            "catalogo_no_disponible",
                            extra={"handler": handler, "status": resp.status_code},
                        )
                        return clave, []
                    return clave, _unwrap_data(resp.json())
                except (PortalUnavailableError, httpx.HTTPError, ValueError) as exc:
                    logger.warning(
                        "catalogo_no_disponible",
                        extra={"handler": handler, "error": str(exc)},
                    )
                    return clave, []

            # Los 7 catálogos en paralelo: en serie el peor caso rozaba el
            # timeout de request de Cloud Run.
            pares = await asyncio.gather(
                *(_pedir(clave, handler) for clave, handler in _CATALOGO_HANDLERS.items())
            )

        for clave, valores in pares:
            resultado[clave] = valores

        vacios = [clave for clave, valores in pares if not valores]
        if vacios:
            resultado["message"] = f"Catálogos no disponibles en el portal: {', '.join(vacios)}"

        return resultado

    # ------------------------------------------------------------------ #
    # Radicación
    # ------------------------------------------------------------------ #

    async def crear_pqrsd(
        self,
        tipo_correspondencia_json: Dict[str, Any],
        dependencia_json: Dict[str, Any],
        asunto: str,
        email: str,
        telefono_celular: str,
        es_anonimo: bool = True,
        numero_identificacion: Optional[str] = None,
        condicion_discapacidad_json: Optional[Dict[str, Any]] = None,
        grupo_etnico_json: Optional[Dict[str, Any]] = None,
        grupo_interes_json: Optional[Dict[str, Any]] = None,
        atencion_preferencial_json: Optional[Dict[str, Any]] = None,
        medio_respuesta_json: Optional[Dict[str, Any]] = None,
        rango_edad_json: Optional[Dict[str, Any]] = None,
        placa: Optional[str] = None,
        archivos_binarios: Optional[List[Tuple[str, bytes, str]]] = None,
    ) -> Dict[str, Any]:
        url = self._settings.portal_radicacion_url

        async with self._client() as client:
            try:
                token, _ = await self._cargar_token(client, url)
            except PortalUnavailableError as exc:
                logger.error("radicacion_token_fallida", extra={"error": str(exc)})
                return {"success": False, "message": str(exc)}

            data = {
                "__RequestVerificationToken": token,
                "Correspondencia.MetodoRecepcion": "Portal web",
                "Correspondencia.TipoCorrespondenciaSerializada": json.dumps(tipo_correspondencia_json),
                "Correspondencia.Asunto": asunto,
                "Correspondencia.DependenciaSerializada": json.dumps(dependencia_json),
                "Correspondencia.Email": email,
                "Correspondencia.TelefonoCelular": telefono_celular,
                "Correspondencia.CondicionDiscapacidadSerializada": json.dumps(
                    condicion_discapacidad_json or {"Id": 1, "Nombre": "No"}
                ),
                "Correspondencia.GrupoEtnicoSerializado": json.dumps(
                    grupo_etnico_json or {"Id": 1, "Nombre": "No"}
                ),
                "Correspondencia.GrupoInteresSerializado": json.dumps(
                    grupo_interes_json or {"Id": 1, "Nombre": "No"}
                ),
                "Correspondencia.AtencionPreferencialSerializada": json.dumps(
                    atencion_preferencial_json or {"Id": 1, "Nombre": "No"}
                ),
                "Correspondencia.MedioRespuestaSerializada": json.dumps(
                    medio_respuesta_json or {"Id": 1, "Nombre": "Virtual"}
                ),
                "Correspondencia.RangoEdadSerializada": json.dumps(
                    rango_edad_json or {"Id": 1, "Nombre": "Adulto"}
                ),
            }

            if placa:
                data["Correspondencia.Placa"] = placa

            if not es_anonimo and numero_identificacion:
                data["Correspondencia.RemitenteSerializado"] = numero_identificacion

            files = [
                ("Correspondencia.Files", (nombre, contenido, tipo or "application/octet-stream"))
                for nombre, contenido, tipo in (archivos_binarios or [])
            ]

            try:
                # Sin reintento: reenviar duplicaría el radicado en el portal.
                resp = await client.post(
                    f"{url}?handler=GenerarRadicado", data=data, files=files or None
                )
            except httpx.HTTPError as exc:
                logger.error("radicacion_fallida", extra={"error": str(exc)})
                return {
                    "success": False,
                    "message": (
                        "Error de comunicación con el portal Neptuno durante la "
                        f"radicación: {exc}. Verifique en el portal si el radicado "
                        "quedó creado antes de reintentar."
                    ),
                }

            if resp.status_code != 200:
                return {
                    "success": False,
                    "message": f"Error al generar radicado en Neptuno: HTTP {resp.status_code}",
                }

            try:
                result_json = resp.json()
            except ValueError:
                return {
                    "success": False,
                    "message": "El portal Neptuno devolvió una respuesta no interpretable",
                }

            item1 = result_json.get("Item1") or {}
            corresp = item1.get("Correspondencia") or {}

            radicado = corresp.get("Radicado") or str(corresp.get("Id") or "")
            codigo = corresp.get("CodigoAutenticacion")

            if not radicado:
                logger.error("radicacion_sin_radicado")
                return {
                    "success": False,
                    "message": "El portal no devolvió un número de radicado",
                }

            logger.info("radicacion_exitosa", extra={"radicado": radicado})

            respuesta: Dict[str, Any] = {
                "success": True,
                "radicado": radicado,
                "codigo_autenticacion": codigo,
                "fecha_radicacion": corresp.get("FechaRadiacion") or corresp.get("FechaRadicacion"),
                "message": (
                    f"Correspondencia registrada bajo el radicado {radicado}, "
                    f"con código de autenticación {codigo}"
                ),
            }

            # El payload crudo contiene datos personales del ciudadano: solo se
            # expone si se habilita explícitamente (diagnóstico en dev).
            if self._settings.expose_raw_response:
                respuesta["raw_response"] = result_json

            return respuesta


_service: Optional[PQRSDRPAService] = None


def get_pqrsd_service() -> PQRSDRPAService:
    """Dependencia FastAPI; los tests la sustituyen vía dependency_overrides."""
    global _service
    if _service is None:
        _service = PQRSDRPAService()
    return _service

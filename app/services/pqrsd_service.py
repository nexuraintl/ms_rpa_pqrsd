import requests
import re
import json
import logging
from typing import Dict, Any, List, Optional
from app.config import settings

logger = logging.getLogger(__name__)

class PQRSDRPAService:
    """
    Servicio RPA para interactuar con la plataforma Suite Neptuno / Alcaldía de Floridablanca.
    Soporta consulta, obtención de catálogos y radicación real de PQRSD.
    """

    def __init__(self):
        self.consulta_url = settings.PORTAL_BASE_URL
        self.radicacion_url = "https://portal.floridablanca.suiteneptuno.com/Correspondencia/Radicacion/Radicacion"
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'X-Requested-With': 'XMLHttpRequest'
        }

    def consultar(self, radicado: str, codigo_autenticacion: str) -> Dict[str, Any]:
        session = requests.Session()

        try:
            resp_get = session.get(self.consulta_url, headers=self.headers, timeout=settings.TIMEOUT)
            if resp_get.status_code != 200:
                return {
                    "success": False,
                    "found": False,
                    "message": f"No se pudo conectar con el portal Neptuno. HTTP {resp_get.status_code}"
                }

            token_match = re.search(r'name="__RequestVerificationToken"\s+type="hidden"\s+value="([^"]+)"', resp_get.text)
            if not token_match:
                return {
                    "success": False,
                    "found": False,
                    "message": "No se pudo extraer el token CSRF de la plataforma"
                }

            token = token_match.group(1)

            payload_buscar = {
                "correspodencia[Radicado]": radicado,
                "correspodencia[CodigoAutenticacion]": codigo_autenticacion,
                "__RequestVerificationToken": token
            }

            url_buscar = f"{self.consulta_url}?handler=BuscarCorrespondencia"
            resp_buscar = session.post(url_buscar, data=payload_buscar, headers=self.headers, timeout=settings.TIMEOUT)

            if resp_buscar.status_code != 200:
                return {
                    "success": False,
                    "found": False,
                    "message": f"Respuesta inesperada al consultar correspondencia: HTTP {resp_buscar.status_code}"
                }

            data_buscar = resp_buscar.json()
            correspondencia = data_buscar.get("Correspondencia")

            if not correspondencia:
                return {
                    "success": True,
                    "found": False,
                    "message": "No se encontró un registro con los datos ingresados. Verifique Radicado y Código."
                }

            radicado_id = correspondencia.get("Id")

            anexos = []
            try:
                url_anexos = f"{self.consulta_url}?handler=ListaAnexos"
                resp_anexos = session.get(
                    url_anexos,
                    params={"radicado": radicado, "radicadoId": radicado_id, "__RequestVerificationToken": token},
                    headers=self.headers,
                    timeout=settings.TIMEOUT
                )
                if resp_anexos.status_code == 200:
                    anexos_raw = resp_anexos.json()
                    if isinstance(anexos_raw, dict) and "data" in anexos_raw:
                        anexos = anexos_raw["data"]
                    elif isinstance(anexos_raw, list):
                        anexos = anexos_raw
            except Exception as e:
                logger.error(f"Error obteniendo anexos: {e}")

            flujo = []
            try:
                url_flujo = f"{self.consulta_url}?handler=FlujoCorrespondencia"
                resp_flujo = session.get(
                    url_flujo,
                    params={"radicado": radicado, "radicadoId": radicado_id, "__RequestVerificationToken": token},
                    headers=self.headers,
                    timeout=settings.TIMEOUT
                )
                if resp_flujo.status_code == 200:
                    flujo_raw = resp_flujo.json()
                    if isinstance(flujo_raw, dict) and "data" in flujo_raw:
                        flujo = flujo_raw["data"]
                    elif isinstance(flujo_raw, list):
                        flujo = flujo_raw
            except Exception as e:
                logger.error(f"Error obteniendo flujo: {e}")

            remitente_obj = correspondencia.get("Remitente") or {}
            estado_obj = correspondencia.get("EstadoCorrespondencia") or {}
            tipo_obj = correspondencia.get("TipoCorrespondencia") or {}

            datos = {
                "id": correspondencia.get("Id"),
                "radicado": correspondencia.get("Radicado"),
                "estado": estado_obj.get("Estado"),
                "tipo_correspondencia": tipo_obj.get("Nombre"),
                "fecha_radicacion": correspondencia.get("FechaRadiacion"),
                "metodo_recepcion": correspondencia.get("MetodoRecepcion"),
                "remitente": remitente_obj.get("NombreConcatenado"),
                "email": remitente_obj.get("Email"),
                "asunto": correspondencia.get("Asunto"),
                "respuesta": correspondencia.get("Respuesta")
            }

            return {
                "success": True,
                "found": True,
                "message": "Consulta realizada exitosamente",
                "datos_correspondencia": datos,
                "anexos": anexos,
                "flujo": flujo
            }

        except Exception as e:
            logger.exception(f"Error interno en servicio RPA: {e}")
            return {
                "success": False,
                "found": False,
                "message": f"Error interno en servicio RPA: {str(e)}"
            }

    def obtener_catalogos(self) -> Dict[str, Any]:
        """
        Consulta los catálogos y listas desplegables en tiempo real desde Neptuno.
        """
        session = requests.Session()
        session.get(self.radicacion_url, headers=self.headers, timeout=settings.TIMEOUT)

        handlers = {
            "tipos_correspondencia": "ListaTipoCorrespondencia",
            "dependencias_areas": "ListaArea",
            "condiciones_discapacidad": "ListaCondicionDiscapacidad",
            "grupos_etnicos": "ListaGrupoEtnico",
            "grupos_interes": "ListaGrupoInteres",
            "atencion_preferencial": "ListaAtencionPreferencial",
            "medios_respuesta": "ListaMedioRespuesta"
        }

        resultados = {"success": True}
        for key, handler in handlers.items():
            try:
                res = session.get(f"{self.radicacion_url}?handler={handler}", headers=self.headers, timeout=settings.TIMEOUT)
                if res.status_code == 200:
                    resultados[key] = res.json().get("data", [])
                else:
                    resultados[key] = []
            except Exception as e:
                logger.error(f"Error al obtener catálogo {handler}: {e}")
                resultados[key] = []

        return resultados

    def crear_pqrsd(
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
        archivos_binarios: List[tuple] = None
    ) -> Dict[str, Any]:
        """
        Envía la radicación real al portal Neptuno mediante POST multipart/form-data al handler GenerarRadicado.
        """
        session = requests.Session()

        try:
            # Step 1: Obtener la página para extraer __RequestVerificationToken y Cookie de sesión
            resp_get = session.get(self.radicacion_url, headers=self.headers, timeout=settings.TIMEOUT)
            if resp_get.status_code != 200:
                return {"success": False, "message": f"No se pudo cargar la página de radicación: HTTP {resp_get.status_code}"}

            token_match = re.search(r'name="__RequestVerificationToken"\s+type="hidden"\s+value="([^"]+)"', resp_get.text)
            if not token_match:
                return {"success": False, "message": "No se pudo extraer el token de verificación CSRF"}

            token = token_match.group(1)

            # Step 2: Construir el payload de datos multipart
            data = {
                "__RequestVerificationToken": token,
                "Correspondencia.MetodoRecepcion": "Portal web",
                "Correspondencia.TipoCorrespondenciaSerializada": json.dumps(tipo_correspondencia_json),
                "Correspondencia.Asunto": asunto,
                "Correspondencia.DependenciaSerializada": json.dumps(dependencia_json),
                "Correspondencia.Email": email,
                "Correspondencia.TelefonoCelular": telefono_celular,
                "Correspondencia.CondicionDiscapacidadSerializada": json.dumps(condicion_discapacidad_json or {"Id": 1, "Nombre": "No"}),
                "Correspondencia.GrupoEtnicoSerializado": json.dumps(grupo_etnico_json or {"Id": 1, "Nombre": "No"}),
                "Correspondencia.GrupoInteresSerializado": json.dumps(grupo_interes_json or {"Id": 1, "Nombre": "No"}),
                "Correspondencia.AtencionPreferencialSerializada": json.dumps(atencion_preferencial_json or {"Id": 1, "Nombre": "No"}),
                "Correspondencia.MedioRespuestaSerializada": json.dumps(medio_respuesta_json or {"Id": 1, "Nombre": "Virtual"}),
                "Correspondencia.RangoEdadSerializada": json.dumps(rango_edad_json or {"Id": 1, "Nombre": "Adulto"})
            }

            if placa:
                data["Correspondencia.Placa"] = placa

            if not es_anonimo and numero_identificacion:
                data["Correspondencia.RemitenteSerializado"] = numero_identificacion

            # Attach files under key 'Correspondencia.Files'
            files_payload = []
            if archivos_binarios:
                for filename, file_content, content_type in archivos_binarios:
                    files_payload.append(
                        ("Correspondencia.Files", (filename, file_content, content_type or "application/octet-stream"))
                    )

            # Step 3: POST a GenerarRadicado
            url_generar = f"{self.radicacion_url}?handler=GenerarRadicado"
            headers_post = {
                'User-Agent': self.headers['User-Agent'],
                'X-Requested-With': 'XMLHttpRequest'
            }

            resp_post = session.post(url_generar, data=data, files=files_payload, headers=headers_post, timeout=settings.TIMEOUT)

            if resp_post.status_code != 200:
                return {
                    "success": False,
                    "message": f"Error al generar radicado en Neptuno: HTTP {resp_post.status_code}",
                    "raw_response": resp_post.text[:1000]
                }

            result_json = resp_post.json()

            # Neptuno returns json result containing generated radicado info
            return {
                "success": True,
                "radicado": result_json.get("Radicado") or result_json.get("numRadicado") or str(result_json.get("Id")),
                "codigo_autenticacion": result_json.get("CodigoAutenticacion") or result_json.get("codigo"),
                "fecha_radicacion": result_json.get("FechaRadicacion"),
                "message": "Radicación realizada exitosamente en el portal de Floridablanca.",
                "raw_response": result_json
            }

        except Exception as e:
            logger.exception(f"Error ejecutando radicación en Neptuno: {e}")
            return {
                "success": False,
                "message": f"Error ejecutando radicación: {str(e)}"
            }

pqrsd_service = PQRSDRPAService()

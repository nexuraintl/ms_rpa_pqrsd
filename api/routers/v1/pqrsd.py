"""Endpoints de negocio del RPA de PQRSD, versionados bajo /v1."""

import json
import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status

from api.core.config import Settings, get_settings
from api.models.schemas import (
    CatalogosResponse,
    ConsultaPQRSDRequest,
    ConsultaPQRSDResponse,
    CrearPQRSDResponse,
)
from api.services.pqrsd_service import PQRSDRPAService, get_pqrsd_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/pqrsd", tags=["PQRSD"])

_CHUNK_SIZE = 64 * 1024


def _parse_json_form(valor: str, campo: str, defecto_id: int) -> Dict[str, Any]:
    """Acepta el objeto serializado del catálogo o, como cortesía, solo el nombre."""
    try:
        parsed = json.loads(valor)
    except (TypeError, ValueError):
        return {"Id": defecto_id, "Nombre": valor}

    if not isinstance(parsed, dict):
        return {"Id": defecto_id, "Nombre": str(parsed)}
    if "Id" not in parsed:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"El campo '{campo}' debe incluir la clave 'Id'. Consulte /v1/pqrsd/catalogos.",
        )
    return parsed


async def _leer_archivo(upload: UploadFile, max_bytes: int) -> bytes:
    """Lee el archivo por trozos y aborta si supera el límite configurado.

    Leer sin tope permitiría que un único request agote la memoria de la
    instancia de Cloud Run.
    """
    partes: List[bytes] = []
    total = 0
    while True:
        chunk = await upload.read(_CHUNK_SIZE)
        if not chunk:
            break
        total += len(chunk)
        if total > max_bytes:
            raise HTTPException(
                status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                detail=(
                    f"El archivo '{upload.filename}' supera el máximo permitido "
                    f"de {max_bytes // (1024 * 1024)} MB."
                ),
            )
        partes.append(chunk)
    return b"".join(partes)


@router.get(
    "/catalogos",
    response_model=CatalogosResponse,
    operation_id="obtenerCatalogosPqrsd",
    summary="Obtener listas desplegables y catálogos",
    description=(
        "Consulta desde el portal Neptuno los tipos de correspondencia, "
        "dependencias/áreas y listas de caracterización. El resultado se cachea "
        "en memoria durante CATALOGOS_CACHE_TTL_SECONDS."
    ),
)
async def obtener_catalogos(
    refrescar: bool = False,
    service: PQRSDRPAService = Depends(get_pqrsd_service),
) -> Dict[str, Any]:
    return await service.obtener_catalogos(forzar_refresco=refrescar)


@router.post(
    "/consultar",
    response_model=ConsultaPQRSDResponse,
    operation_id="consultarPqrsd",
    summary="Consultar PQRSD por radicado y código",
    description=(
        "Consulta el portal Neptuno y retorna estado, datos, anexos y flujo de "
        "trazabilidad del radicado."
    ),
)
async def consultar_pqrsd(
    payload: ConsultaPQRSDRequest,
    service: PQRSDRPAService = Depends(get_pqrsd_service),
) -> Dict[str, Any]:
    resultado = await service.consultar(
        radicado=payload.radicado,
        codigo_autenticacion=payload.codigo_autenticacion,
    )
    if not resultado["success"]:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail=resultado["message"]
        )
    return resultado


@router.post(
    "/crear",
    response_model=CrearPQRSDResponse,
    operation_id="crearPqrsd",
    summary="Crear/radicar PQRSD en Neptuno",
    description=(
        "Radica una PQRSD en el portal oficial. Admite radicación anónima o "
        "identificada y archivos anexos."
    ),
)
async def crear_pqrsd(
    tipo_correspondencia_json_str: str = Form(
        '{"Id":6,"Nombre":"Petición"}', description="Objeto JSON del tipo de correspondencia"
    ),
    dependencia_json_str: str = Form(
        '{"Id":1,"Nombre":"Despacho"}', description="Objeto JSON del área/dependencia destinataria"
    ),
    asunto: str = Form(..., min_length=1, description="Asunto o contenido detallado de la solicitud"),
    email: str = Form(..., min_length=1, description="Correo electrónico de contacto"),
    telefono_celular: str = Form(..., min_length=1, description="Teléfono celular de contacto"),
    es_anonimo: bool = Form(True, description="True si es radicación anónima"),
    numero_identificacion: Optional[str] = Form(
        None, description="Número de documento (si es_anonimo=False)"
    ),
    placa: Optional[str] = Form(None, description="Placa del vehículo (opcional)"),
    archivos: List[UploadFile] = File(default=[], description="Archivos anexos"),
    service: PQRSDRPAService = Depends(get_pqrsd_service),
    settings: Settings = Depends(get_settings),
) -> Dict[str, Any]:
    tipo_json = _parse_json_form(tipo_correspondencia_json_str, "tipo_correspondencia_json_str", 6)
    dependencia_json = _parse_json_form(dependencia_json_str, "dependencia_json_str", 1)

    if not es_anonimo and not numero_identificacion:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Para una radicación identificada se requiere 'numero_identificacion'.",
        )

    archivos = [a for a in archivos if a.filename]

    if len(archivos) > settings.max_upload_files:
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail=f"Máximo {settings.max_upload_files} archivos por radicación.",
        )

    archivos_binarios = []
    total = 0
    for archivo in archivos:
        contenido = await _leer_archivo(archivo, settings.max_upload_bytes)
        total += len(contenido)
        if total > settings.max_upload_total_bytes:
            raise HTTPException(
                status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                detail=(
                    "El tamaño total de los anexos supera el máximo de "
                    f"{settings.max_upload_total_bytes // (1024 * 1024)} MB."
                ),
            )
        archivos_binarios.append((archivo.filename, contenido, archivo.content_type))

    resultado = await service.crear_pqrsd(
        tipo_correspondencia_json=tipo_json,
        dependencia_json=dependencia_json,
        asunto=asunto,
        email=email,
        telefono_celular=telefono_celular,
        es_anonimo=es_anonimo,
        numero_identificacion=numero_identificacion,
        placa=placa,
        archivos_binarios=archivos_binarios,
    )

    if not resultado["success"]:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail=resultado["message"]
        )
    return resultado

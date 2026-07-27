from fastapi import FastAPI, HTTPException, status, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from typing import List, Optional
import json
from app.config import settings
from app.models.schemas import (
    ConsultaPQRSDRequest,
    ConsultaPQRSDResponse,
    CatalogosResponse,
    CrearPQRSDResponse
)
from app.services.pqrsd_service import pqrsd_service

app = FastAPI(
    title=settings.PROJECT_NAME,
    version=settings.VERSION,
    description=settings.DESCRIPTION,
    docs_url="/docs",
    redoc_url="/redoc"
)

# CORS middleware for microservice compatibility
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/", tags=["Health Check"])
def root():
    return {
        "status": "online",
        "service": settings.PROJECT_NAME,
        "version": settings.VERSION,
        "docs": "/docs"
    }

@app.get("/health", tags=["Health Check"])
def health_check():
    return {"status": "ok"}

@app.get(
    "/api/v1/pqrsd/catalogos",
    response_model=CatalogosResponse,
    tags=["PQRSD RPA"],
    summary="Obtener listas desplegables y catálogos en tiempo real",
    description="Consulta en tiempo real desde el portal Neptuno los tipos de correspondencia (Petición, Queja, etc.), dependencias/áreas y listas de caracterización."
)
def obtener_catalogos():
    return pqrsd_service.obtener_catalogos()

@app.post(
    "/api/v1/pqrsd/consultar",
    response_model=ConsultaPQRSDResponse,
    tags=["PQRSD RPA"],
    summary="Consultar PQRSD por Radicado y Código (Imagen 1)",
    description="Interactúa automáticamente con el Portal Suite Neptuno (Floridablanca) y retorna la información detallada del radicado."
)
def consultar_pqrsd(payload: ConsultaPQRSDRequest):
    resultado = pqrsd_service.consultar(
        radicado=payload.radicado,
        codigo_autenticacion=payload.codigo_autenticacion
    )
    if not resultado["success"]:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=resultado["message"]
        )
    return resultado

@app.post(
    "/api/v1/pqrsd/crear",
    response_model=CrearPQRSDResponse,
    tags=["PQRSD RPA"],
    summary="Crear/Radicar PQRSD en Neptuno (Multipart Form)",
    description="Procesa la radicación oficial de una PQRSD en el portal Neptuno con los datos seleccionados y archivos físicos adjuntos."
)
async def crear_pqrsd(
    tipo_correspondencia_json_str: str = Form('{"Id":6,"Nombre":"Petición"}', description="Objeto JSON del tipo de correspondencia"),
    dependencia_json_str: str = Form('{"Id":1,"Nombre":"Despacho"}', description="Objeto JSON del área/dependencia destinataria"),
    asunto: str = Form(..., description="Asunto o contenido detallado de la solicitud"),
    email: str = Form(..., description="Correo electrónico de contacto"),
    telefono_celular: str = Form(..., description="Teléfono celular de contacto"),
    es_anonimo: bool = Form(True, description="True si es radicación anónima, False si es identificada"),
    numero_identificacion: Optional[str] = Form(None, description="Número de documento (si es_anonimo=False)"),
    placa: Optional[str] = Form(None, description="Placa del vehículo (opcional)"),
    archivos: List[UploadFile] = File(default=[], description="Archivos anexos físicos (PDFs, imágenes, documentos)")
):
    try:
        tipo_json = json.loads(tipo_correspondencia_json_str)
    except Exception:
        tipo_json = {"Id": 6, "Nombre": tipo_correspondencia_json_str}

    try:
        dependencia_json = json.loads(dependencia_json_str)
    except Exception:
        dependencia_json = {"Id": 1, "Nombre": dependencia_json_str}

    archivos_binarios = []
    for a in archivos:
        content = await a.read()
        archivos_binarios.append((a.filename, content, a.content_type))

    resultado = pqrsd_service.crear_pqrsd(
        tipo_correspondencia_json=tipo_json,
        dependencia_json=dependencia_json,
        asunto=asunto,
        email=email,
        telefono_celular=telefono_celular,
        es_anonimo=es_anonimo,
        numero_identificacion=numero_identificacion,
        placa=placa,
        archivos_binarios=archivos_binarios
    )
    return resultado

from pydantic import BaseModel, Field
from typing import Optional, List, Any, Dict

# --- CONSULTA MODELS (IMAGEN 1 -> IMAGEN 2) ---
class ConsultaPQRSDRequest(BaseModel):
    radicado: str = Field(..., description="Número de radicado de la correspondencia/PQRSD", example="2024010101")
    codigo_autenticacion: str = Field(..., description="Código de autenticación entregado al radicar", example="123456")

class DatosCorrespondencia(BaseModel):
    id: Optional[int] = Field(None, description="ID interno de la correspondencia")
    radicado: str = Field(..., description="Número de radicado")
    estado: Optional[str] = Field(None, description="Estado de la correspondencia")
    tipo_correspondencia: Optional[str] = Field(None, description="Tipo de correspondencia (PQRSD, etc.)")
    fecha_radicacion: Optional[str] = Field(None, description="Fecha de radicación del trámite")
    metodo_recepcion: Optional[str] = Field(None, description="Método de recepción")
    remitente: Optional[str] = Field(None, description="Nombre del remitente")
    email: Optional[str] = Field(None, description="Email del remitente")
    asunto: Optional[str] = Field(None, description="Asunto de la correspondencia")
    respuesta: Optional[str] = Field(None, description="Respuesta dada al radicado")

class ConsultaPQRSDResponse(BaseModel):
    success: bool = Field(..., description="Indica si la solicitud a la plataforma fue exitosa")
    found: bool = Field(..., description="Indica si se encontró información para el radicado")
    message: Optional[str] = Field(None, description="Mensaje informativo o de error")
    datos_correspondencia: Optional[DatosCorrespondencia] = Field(None, description="Datos principales de la correspondencia")
    anexos: List[Dict[str, Any]] = Field(default_factory=list, description="Lista de anexos asociados")
    flujo: List[Dict[str, Any]] = Field(default_factory=list, description="Historial de flujo de correspondencia")


# --- CATALOGOS MODELS ---
class CatalogosResponse(BaseModel):
    success: bool
    tipos_correspondencia: List[Dict[str, Any]] = Field(default_factory=list, description="Tipos de PQRSD (Petición, Queja, etc.)")
    dependencias_areas: List[Dict[str, Any]] = Field(default_factory=list, description="Áreas destinatarias (Despacho, Jurídica, etc.)")
    condiciones_discapacidad: List[Dict[str, Any]] = Field(default_factory=list)
    grupos_etnicos: List[Dict[str, Any]] = Field(default_factory=list)
    grupos_interes: List[Dict[str, Any]] = Field(default_factory=list)
    atencion_preferencial: List[Dict[str, Any]] = Field(default_factory=list)
    medios_respuesta: List[Dict[str, Any]] = Field(default_factory=list)


# --- CREACIÓN / RADICACIÓN MODELS ---
class CrearPQRSDResponse(BaseModel):
    success: bool = Field(..., description="Indica si la radicación fue exitosa")
    radicado: Optional[str] = Field(None, description="Número de radicado asignado por Neptuno")
    codigo_autenticacion: Optional[str] = Field(None, description="Código de autenticación generado para consulta")
    fecha_radicacion: Optional[str] = Field(None, description="Fecha y hora de radicación")
    message: str = Field(..., description="Mensaje devuelto por la plataforma")
    raw_response: Optional[Dict[str, Any]] = Field(None, description="Respuesta completa del portal Neptuno")

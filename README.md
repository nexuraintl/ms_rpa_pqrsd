# Microservicio RPA PQRSD - Alcaldía de Floridablanca (Suite Neptuno)

Microservicio en **FastAPI** para la automatización e integración (RPA) del Portal de Correspondencia y PQRSD de la Alcaldía Municipal de Floridablanca.

---

## 📌 Funcionalidades

### 1. Obtener Catálogos y Desplegables (`GET /api/v1/pqrsd/catalogos`)
Consulta en tiempo real desde el portal Neptuno los desplegables necesarios para llenar el formulario:
- **Tipos de correspondencia** (Petición, Queja, Reclamo, etc.) con sus IDs.
- **Áreas / Dependencias destinatarias** (Despacho, Asesora Jurídica, etc.).
- Listas de caracterización poblacional y medios de respuesta.

### 2. Consultar PQRSD (`POST /api/v1/pqrsd/consultar`)
- Recibe `radicado` y `codigo_autenticacion` (**Imagen 1**).
- Extrae y retorna todos los datos (**Imagen 2**): Estado, Tipo, Fecha, Remitente, Email, Asunto, Respuesta, Anexos y Flujo de trazabilidad.

### 3. Crear / Radicar PQRSD (`POST /api/v1/pqrsd/crear`)
- Procesa la radicación oficial en el portal enviando la información a `?handler=GenerarRadicado`.
- Soporta radicación **anónima** o **identificada** con número de documento.
- Permite adjuntar archivos físicos reales (`archivos`: UploadFile).

---

## 🛠️ Instalación y Ejecución

```bash
# Crear e ingresar al entorno virtual
python -m venv .venv
.\.venv\Scripts\Activate.ps1

# Instalación de dependencias
pip install -r requirements.txt

# Iniciar servidor FastAPI
uvicorn app.main:app --reload --port 8000
```

Acceso a Swagger UI: [http://localhost:8000/docs](http://localhost:8000/docs)

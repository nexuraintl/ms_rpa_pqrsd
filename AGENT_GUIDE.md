# Guía de integración para agentes IA y desarrolladores

Guía técnica para consumir los endpoints del microservicio RPA de PQRSD
(`ms_rpa_pqrsd`, Alcaldía de Floridablanca / Suite Neptuno).

> **Cambio de rutas.** Las rutas pasaron de `/api/v1/pqrsd/...` a
> `/v1/pqrsd/...` al adoptar GOB-GCP-STD-01. Detrás del API Gateway el prefijo
> del módulo lo agrega el gateway: `/rpa/pqrsd/v1/...`.

---

## Información general

| | |
|---|---|
| Base URL (local) | `http://localhost:8000` |
| Base URL (Cloud Run) | `https://<ambiente>-rpa-pqrsd-<hash>.run.app` |
| Base URL (Gateway) | `https://<gateway-host>/rpa/pqrsd` |
| Formato | REST / JSON / multipart-form-data |
| Swagger UI | `/docs` |
| OpenAPI | `/openapi.json` — también versionado en `openapi/openapi.yaml` |

**Autenticación.** El servicio se despliega siempre con
`--no-allow-unauthenticated`. Vía Cloud Run directo, enviar un token de
identidad de Google; vía gateway, el JWT de la service account autorizada:

```
Authorization: Bearer <token>
```

**Trazabilidad.** Toda respuesta incluye `X-Correlation-ID`. Si lo envías en el
request, el servicio lo propaga; si no, genera uno. Guárdalo: es la clave para
localizar el request en Cloud Logging.

---

## Endpoints

| Endpoint | Método | Payload | Descripción |
|---|---|---|---|
| `/v1/pqrsd/catalogos` | GET | — | Listas desplegables (áreas, tipos de PQRSD) |
| `/v1/pqrsd/consultar` | POST | `application/json` | Estado, anexos y flujo de un radicado |
| `/v1/pqrsd/crear` | POST | `multipart/form-data` | Radica una nueva PQRSD |
| `/health` | GET | — | Liveness |
| `/version` | GET | — | Versión y ambiente desplegados |

---

## 1. Consultar PQRSD — `POST /v1/pqrsd/consultar`

**Request**

```json
{
  "radicado": "2026488450",
  "codigo_autenticacion": "202UhXbRIu2026488450"
}
```

**Response 200**

```json
{
  "success": true,
  "found": true,
  "message": "Consulta realizada exitosamente",
  "datos_correspondencia": {
    "id": 488450,
    "radicado": "2026488450",
    "estado": "En revisión",
    "tipo_correspondencia": "Otro",
    "fecha_radicacion": "2026-07-29T07:10:00",
    "metodo_recepcion": "Portal web",
    "remitente": "ANÓNIMO",
    "email": "sincorreo@gmail.com",
    "asunto": "Prueba de Nexura",
    "respuesta": null
  },
  "anexos": [
    { "Procedencia": "Documento Adjunto", "NombreArchivo": "soporte.pdf" }
  ],
  "flujo": [
    {
      "Responsable": {
        "NombreConcatenado": "EDGAR MAURICIO PEÑUELA ARCE",
        "Cargo": "Secretaría General",
        "Area": "Secretaría General",
        "Email": "sec.general@floridablanca.gov.co"
      },
      "FechaAsignacionString": "29/07/26 7:10 a. m.",
      "FechaRespuestaString": ""
    }
  ]
}
```

**Radicado inexistente — también 200.** Distinguir por `found`, no por el
código HTTP:

```json
{
  "success": true,
  "found": false,
  "message": "No se encontró un registro con los datos ingresados. Verifique Radicado y Código.",
  "datos_correspondencia": null,
  "anexos": [],
  "flujo": []
}
```

`anexos` y `flujo` pueden venir vacíos aunque la consulta sea exitosa: son
secciones accesorias y su indisponibilidad degrada la respuesta sin invalidarla.

---

## 2. Radicar PQRSD — `POST /v1/pqrsd/crear`

`Content-Type: multipart/form-data`.

| Campo | Tipo | Requerido | Ejemplo |
|---|---|---|---|
| `asunto` | string | **Sí** | `"Solicitud de información sobre el trámite..."` |
| `email` | string | **Sí** | `"usuario@ejemplo.com"` |
| `telefono_celular` | string | **Sí** | `"3001234567"` |
| `tipo_correspondencia_json_str` | string (JSON) | No (default Id 6) | `{"Id": 6, "Nombre": "Petición"}` |
| `dependencia_json_str` | string (JSON) | No (default Id 1) | `{"Id": 8, "Nombre": "Secretaría General"}` |
| `es_anonimo` | boolean | No (default `true`) | `false` para identificada |
| `numero_identificacion` | string | Sí si `es_anonimo=false` | `"1098765432"` |
| `placa` | string | No | `"ABC123"` |
| `archivos` | file[] | No | Uno o varios anexos |

Los `Id` válidos salen de `/v1/pqrsd/catalogos`.

**Límites de anexos** (configurables, valores por defecto): 10 archivos,
10 MB por archivo, 25 MB en total. Excederlos devuelve **413**.

**Response 200**

```json
{
  "success": true,
  "radicado": "2026488452",
  "codigo_autenticacion": "2025jRhhE22026488452",
  "fecha_radicacion": "2026-07-29T07:10:00",
  "message": "Correspondencia registrada bajo el radicado 2026488452, con código de autenticación 2025jRhhE22026488452",
  "raw_response": null
}
```

`raw_response` viene en `null` salvo que se habilite `EXPOSE_RAW_RESPONSE`:
contiene datos personales del ciudadano y permanece oculto en producción.

> **Guardar `radicado` y `codigo_autenticacion` de inmediato.** Son la única
> forma de consultar el trámite después, y el portal no permite recuperarlos.

---

## 3. Catálogos — `GET /v1/pqrsd/catalogos`

```json
{
  "success": true,
  "message": null,
  "tipos_correspondencia": [
    { "Id": 6, "Nombre": "Petición" },
    { "Id": 7, "Nombre": "Queja" }
  ],
  "dependencias_areas": [
    { "Id": 8, "Nombre": "Secretaría General" },
    { "Id": 1, "Nombre": "Despacho" }
  ]
}
```

La respuesta se cachea en memoria (5 minutos por defecto). Para forzar una
lectura fresca: `GET /v1/pqrsd/catalogos?refrescar=true`.

Si `success` es `true` pero `message` trae texto, algunos catálogos no
respondieron y llegan vacíos.

---

## Ejemplos

### Python

```python
import requests

TOKEN = "..."  # token de identidad de Google
BASE = "https://prod-rpa-pqrsd-xxxx.run.app"
headers = {"Authorization": f"Bearer {TOKEN}"}

r = requests.post(
    f"{BASE}/v1/pqrsd/consultar",
    headers=headers,
    json={"radicado": "2026488450", "codigo_autenticacion": "202UhXbRIu2026488450"},
)
data = r.json()

if data["found"]:
    print("Estado:", data["datos_correspondencia"]["estado"])
else:
    print(data["message"])

print("Correlation-ID:", r.headers["X-Correlation-ID"])
```

Radicar con anexo:

```python
respuesta = requests.post(
    f"{BASE}/v1/pqrsd/crear",
    headers=headers,
    data={
        "asunto": "Petición sobre estado de vía pública",
        "email": "ciudadano@gmail.com",
        "telefono_celular": "3109876543",
        "es_anonimo": "true",
        "tipo_correspondencia_json_str": '{"Id": 6, "Nombre": "Petición"}',
        "dependencia_json_str": '{"Id": 8, "Nombre": "Secretaría General"}',
    },
    files=[("archivos", ("foto.jpg", open("foto.jpg", "rb"), "image/jpeg"))],
)
res = respuesta.json()
print("Radicado:", res["radicado"], "| Código:", res["codigo_autenticacion"])
```

### JavaScript

```javascript
const response = await fetch(`${BASE}/v1/pqrsd/consultar`, {
  method: "POST",
  headers: {
    "Content-Type": "application/json",
    Authorization: `Bearer ${token}`,
  },
  body: JSON.stringify({
    radicado: "2026488450",
    codigo_autenticacion: "202UhXbRIu2026488450",
  }),
});
const result = await response.json();
```

---

## Códigos HTTP

| Código | Significado | Acción del cliente |
|---|---|---|
| `200` | Procesado. En `/consultar`, revisar `found` | — |
| `413` | Anexos sobre el límite | Reducir tamaño o cantidad |
| `422` | Validación de entrada | Corregir los campos |
| `500` | Error interno | Reportar con el `correlation_id` |
| `502` | El portal de la Alcaldía no respondió | Reintentar más tarde — **ver aviso** |

> **Aviso sobre 502 en `/v1/pqrsd/crear`.** El servicio no reintenta la
> radicación automáticamente porque duplicaría el trámite. Ante un 502, verificar
> en el portal si el radicado quedó creado **antes** de reenviar.

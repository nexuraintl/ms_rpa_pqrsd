# Guía de integración — ms_rpa_pqrsd

Guía técnica para consumir el microservicio RPA de PQRSD (Alcaldía de
Floridablanca / Suite Neptuno) desde otro servicio, un agente IA o un cliente
HTTP.

> **Cambio de rutas.** Pasaron de `/api/v1/pqrsd/...` a `/v1/pqrsd/...` al
> adoptar GOB-GCP-STD-01. Detrás del API Gateway el prefijo del módulo lo agrega
> el gateway: `/rpa/pqrsd/v1/...`.

---

## 1. Dónde vive el servicio

| Ambiente | URL | Ingress |
|---|---|---|
| QAM | `https://qam-rpa-pqrsd-ghlnutfdwq-uc.a.run.app` | `all` — alcanzable directo |
| PREM | vía gateway | `internal-and-cloud-load-balancing` |
| PROD | vía gateway | `internal-and-cloud-load-balancing` |

Para obtener la URL vigente de cualquier ambiente:

```bash
gcloud run services describe qam-rpa-pqrsd --region=us-central1 --project=pre-qa-functions --format='value(status.url)'
```

**En PREM y PROD el Cloud Run no es alcanzable desde internet.** Solo responde a
través del gateway. Si intentas pegarle directo obtienes un 404 del Google Front
End (HTML), no de la aplicación.

### La URL siempre va en una variable de entorno

Nunca la escribas fija en el código. Dos razones concretas:

- **Cambia por ambiente.** QAM pega al Cloud Run; PREM y PROD al gateway. Son
  hosts distintos, no un sufijo que puedas construir.
- **Cambia si el servicio se recrea.** En este proyecto ya pasó: al renombrar el
  servicio de `qa-rpa-pqrsd` a `qam-rpa-pqrsd`, el hash del host cambió por
  completo. Todo lo que la tuviera fija habría dejado de funcionar sin aviso.

Convención: **`RPA_PQRSD_URL`**, sin barra final. Declárala en el
`.env.example` de tu servicio y resuélvela por ambiente en el despliegue.

Ese mismo valor es el `audience` del identity token, así que un desajuste no te
rompe solo la ruta: te rompe también la autenticación, y el 401 que recibes no
menciona la URL. Por eso los ejemplos de abajo le quitan la barra final al leerla
y fallan al arrancar si la variable no está, en vez de descubrirlo en el primer
request.

| | |
|---|---|
| Formato | REST / JSON / multipart-form-data |
| Swagger UI | `/docs` |
| OpenAPI | `/openapi.json`, versionado en [`openapi/openapi.yaml`](openapi/openapi.yaml) |

---

## 2. Autenticación

El servicio se despliega **siempre** con `--no-allow-unauthenticated`. Radica
trámites reales ante la Alcaldía: nunca se abre al público.

### En producción: el cliente acuña el token, no una persona

Los identity tokens duran 1 hora. Eso es irrelevante en producción porque la
librería de Google los pide y los renueva sola. **Nunca pongas un token
literal en el código ni en una variable de entorno.**

**Si el cliente corre en GCP** (Cloud Run, Cloud Functions, GKE, Compute Engine)
no hacen falta llaves: el servidor de metadatos acuña el token.

```python
import os
import time
import google.auth.transport.requests
import google.oauth2.id_token

# Desde el entorno, nunca fija en el código. `.rstrip` protege el audience:
# una barra final sobrante devuelve 401.
RPA_URL = os.environ["RPA_PQRSD_URL"].rstrip("/")
_cache = {"token": None, "exp": 0.0}


def token_rpa() -> str:
    """Identity token para invocar el RPA. Renueva 5 min antes de expirar."""
    ahora = time.time()
    if _cache["token"] and ahora < _cache["exp"] - 300:
        return _cache["token"]
    peticion = google.auth.transport.requests.Request()
    _cache["token"] = google.oauth2.id_token.fetch_id_token(peticion, RPA_URL)
    _cache["exp"] = ahora + 3600
    return _cache["token"]
```

En Node, `google-auth-library` gestiona caché y renovación internamente:

```javascript
import { GoogleAuth } from 'google-auth-library';

// Desde el entorno, nunca fija en el código.
const RPA_URL = (process.env.RPA_PQRSD_URL ?? '').replace(/\/$/, '');
if (!RPA_URL) throw new Error('Falta la variable de entorno RPA_PQRSD_URL');

const cliente = await new GoogleAuth().getIdTokenClient(RPA_URL);

const r = await cliente.request({
  url: `${RPA_URL}/v1/pqrsd/consultar`,
  method: 'POST',
  data: { radicado: '2026488602', codigo_autenticacion: '...' },
});
```

**Si el cliente corre fuera de GCP**, usa Workload Identity Federation. Una llave
JSON de service account es el último recurso: es una credencial de larga vida
que, si se filtra, permite radicar trámites a nombre del municipio. Si te toca,
va en Secret Manager — nunca en el repositorio ni en una env var plana.

**El error más común:** el `audience` del token debe ser la URL **exacta** del
servicio, sin barra final. Si no coincide, es 401 y el mensaje no te dice que el
problema es el audience.

Permiso para la service account que consume:

```bash
gcloud run services add-iam-policy-binding qam-rpa-pqrsd --region=us-central1 --project=pre-qa-functions --member="serviceAccount:SA-DEL-CLIENTE@proyecto.iam.gserviceaccount.com" --role="roles/run.invoker"
```

### A través del gateway (PREM y PROD)

El cliente no le habla al Cloud Run, le habla al gateway:

```
Cliente ──JWT firmado con su SA (aud = URL del gateway)──▶ API Gateway (ESPv2)
                                                                │
                                          ESPv2 acuña su propio token
                                                                ▼
                                                      Cloud Run privado
```

El cliente firma un JWT con la llave privada de su service account y `aud` igual
al host del **gateway**. Los tres campos que deben calzar
(`x-google-issuer`, `x-google-jwks_uri`, `x-google-audiences`) están en
[`gateway/gateway.yaml`](gateway/gateway.yaml).

### Solo para pruebas manuales

```bash
gcloud auth print-identity-token
```

Es un **identity token** (OIDC). `print-access-token` no sirve: Cloud Run valida
OIDC. Dura una hora; cuando veas 401, vuelve a generarlo.

---

## 3. Endpoints

| Método | Path (Cloud Run) | Path (Gateway) | Auth | Descripción |
|---|---|---|---|---|
| GET | `/health` | `/rpa/pqrsd/health` | No | Liveness |
| GET | `/version` | `/rpa/pqrsd/version` | No | Servicio, versión y ambiente |
| GET | `/v1/pqrsd/catalogos` | `/rpa/pqrsd/v1/catalogos` | Sí | Listas desplegables |
| POST | `/v1/pqrsd/consultar` | `/rpa/pqrsd/v1/consultar` | Sí | Consulta un radicado |
| POST | `/v1/pqrsd/crear` | `/rpa/pqrsd/v1/crear` | Sí | Radica una PQRSD |

Toda respuesta incluye `X-Correlation-ID`. Si lo envías en el request, el
servicio lo propaga; si no, genera uno.

---

## 4. Consultar PQRSD — `POST /v1/pqrsd/consultar`

**Request**

```json
{
  "radicado": "2026488602",
  "codigo_autenticacion": "VL0TBLXzad2026488602"
}
```

**Response 200**

```json
{
  "success": true,
  "found": true,
  "message": "Consulta realizada exitosamente",
  "datos_correspondencia": {
    "id": 488602,
    "radicado": "2026488602",
    "estado": "En revisión",
    "tipo_correspondencia": "Petición",
    "fecha_radicacion": "2026-07-29T07:10:00",
    "metodo_recepcion": "Portal web",
    "remitente": "ANÓNIMO",
    "email": "sincorreo@gmail.com",
    "asunto": "Prueba de integración",
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

**Radicado inexistente — también 200.** Distingue por `found`, no por el código
HTTP:

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

`anexos` y `flujo` pueden llegar vacíos aunque la consulta sea exitosa: son
secciones accesorias y su indisponibilidad degrada la respuesta sin invalidarla.

---

## 5. Radicar PQRSD — `POST /v1/pqrsd/crear`

`Content-Type: multipart/form-data`.

| Campo | Tipo | Requerido | Ejemplo |
|---|---|---|---|
| `asunto` | string | **Sí** | `"Solicitud sobre el trámite..."` |
| `email` | string | **Sí** | `"usuario@ejemplo.com"` |
| `telefono_celular` | string | **Sí** | `"3001234567"` |
| `tipo_correspondencia_json_str` | string (JSON) | No (default Id 6) | `{"Id": 6, "Nombre": "Petición"}` |
| `dependencia_json_str` | string (JSON) | No (default Id 1) | `{"Id": 8, "Nombre": "Secretaría General"}` |
| `es_anonimo` | boolean | No (default `true`) | `false` para identificada |
| `numero_identificacion` | string | Sí si `es_anonimo=false` | `"1098765432"` |
| `placa` | string | No | `"ABC123"` |
| `archivos` | file[] | No | Uno o varios anexos |

Los `Id` válidos salen de `/v1/pqrsd/catalogos`.

**Límites de anexos** (por defecto): 10 archivos, 10 MB cada uno, 25 MB en
total. Excederlos devuelve **413**.

**Response 200**

```json
{
  "success": true,
  "radicado": "2026488602",
  "codigo_autenticacion": "VL0TBLXzad2026488602",
  "fecha_radicacion": "2026-07-29T07:10:00",
  "message": "Correspondencia registrada bajo el radicado 2026488602, con código de autenticación VL0TBLXzad2026488602",
  "raw_response": null
}
```

`raw_response` viene `null` salvo que se habilite `EXPOSE_RAW_RESPONSE`: contiene
datos personales del ciudadano y permanece oculto en producción.

> **Guarda `radicado` y `codigo_autenticacion` de inmediato.** Son la única forma
> de consultar el trámite después, y el portal no permite recuperarlos.

### Este endpoint no es un sandbox

Cada llamada exitosa genera un **trámite oficial real** ante la Alcaldía de
Floridablanca, que alguien tendrá que atender, y no se puede anular desde aquí.
Dos consecuencias para quien integra:

- No lo uses en pruebas automatizadas contra el servicio desplegado. Para
  ejercitar el flujo, simula el portal como hacen los tests del repositorio.
- Ante un **502**, el servicio no reintenta: un reenvío duplicaría el trámite.
  Verifica en el portal si el radicado quedó creado **antes** de reintentar.

Ejemplo con el token ya resuelto por la librería:

```python
import httpx

respuesta = httpx.post(
    f"{RPA_URL}/v1/pqrsd/crear",
    headers={"Authorization": f"Bearer {token_rpa()}"},
    data={
        "asunto": "Petición sobre estado de vía pública",
        "email": "ciudadano@ejemplo.com",
        "telefono_celular": "3109876543",
        "es_anonimo": "true",
        "tipo_correspondencia_json_str": '{"Id": 6, "Nombre": "Petición"}',
        "dependencia_json_str": '{"Id": 8, "Nombre": "Secretaría General"}',
    },
    files=[("archivos", ("soporte.pdf", contenido_pdf, "application/pdf"))],
    timeout=120,
)
res = respuesta.json()
print(res["radicado"], res["codigo_autenticacion"])
```

El `timeout` del cliente debe superar el del servicio (120 s): la radicación
sube anexos y espera al portal.

---

## 6. Catálogos — `GET /v1/pqrsd/catalogos`

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

Se cachea en memoria 5 minutos por instancia. Para forzar lectura fresca:
`?refrescar=true`.

Si `success` es `true` pero `message` trae texto, algunos catálogos no
respondieron y llegan vacíos. Si `success` es `false`, el portal está caído y
todas las listas vienen vacías.

---

## 7. Probar con Postman

1. **Environment** con `baseUrl` = la URL del ambiente.
2. El token va en el **Postman Vault**, no en el Environment: las variables de
   Environment se sincronizan a la nube de Postman. Créalo como
   `gcp-id-token` y refiérelo con `{{vault:gcp-id-token}}`.
3. En la **Authorization de la Collection**: Type `Bearer Token`, valor
   `{{vault:gcp-id-token}}`. Los requests lo heredan.
4. Empieza por `GET {{baseUrl}}/health` — debe devolver `{"status":"UP"}`.
5. `POST {{baseUrl}}/v1/pqrsd/consultar` → Body `raw` / `JSON`.
6. `POST {{baseUrl}}/v1/pqrsd/crear` → Body **`form-data`** (no `raw`, no
   `x-www-form-urlencoded`). Para `archivos`, cambia el tipo de la fila de
   `Text` a `File`.

Postman puede marcar el token como "Supabase Service Role API Key": es un falso
positivo de etiqueta. Los identity tokens de Google y las claves de Supabase son
ambos JWT y empiezan igual (`eyJhbGciOi...`). El de Google usa `RS256` y su `iss`
es `https://accounts.google.com`.

---

## 8. Códigos HTTP y diagnóstico

| Código | Significado | Qué hacer |
|---|---|---|
| `200` | Procesado. En `/consultar`, revisar `found` | — |
| `401` | Token inválido, expirado o con `audience` equivocado | Regenerar; verificar que el audience sea la URL exacta sin barra final |
| `403` | Falta `roles/run.invoker` | Conceder el rol a la SA o usuario |
| `404` con `{"detail":"Not Found"}` | La ruta no existe | Es la app respondiendo: revisa el path contra `/openapi.json` |
| `404` con HTML de Google | El ingress no permite tu tráfico | El servicio es `internal-and-cloud-load-balancing`: entra por el gateway |
| `413` | Anexos sobre el límite | Reducir tamaño o cantidad |
| `422` | Validación de entrada | Corregir los campos |
| `500` | Error interno | Reportar con el `correlation_id` de la respuesta |
| `502` | El portal de la Alcaldía no respondió | Reintentar más tarde — **en `/crear`, verificar primero** |

**La distinción de los dos 404 es la que más tiempo ahorra.** Si el cuerpo es
JSON, la petición llegó a la aplicación y solo está mal el path. Si es HTML, no
pasó del balanceador de Google.

### Rastrear un request

Manda tu propio identificador:

```
X-Correlation-ID: mi-sistema-001
```

Y búscalo en Cloud Logging:

```bash
gcloud logging read 'resource.labels.service_name="qam-rpa-pqrsd" AND jsonPayload.correlation_id="mi-sistema-001"' --project=pre-qa-functions --limit=20 --format='value(jsonPayload.message,jsonPayload.duration_ms)'
```

Los eventos que emite el servicio están en la sección 7 de
[`docs/MANUAL.md`](docs/MANUAL.md).

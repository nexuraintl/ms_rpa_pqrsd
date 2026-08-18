# Manual del servicio — ms_rpa_pqrsd

Documento operativo conforme a **GOB-GCP-STD-01**.

> **Campos marcados `⟨PENDIENTE⟩`**: solo el equipo responsable puede
> completarlos (proyectos GCP, service accounts, responsables). No se
> inventan valores en este manual.

---

## 1. Descripción funcional

| Campo | Valor |
|---|---|
| Nombre del repositorio | `ms_rpa_pqrsd` |
| Módulo | `rpa` |
| Microservicio | `pqrsd` |
| Responsable funcional | ⟨PENDIENTE⟩ |
| Responsable técnico | ⟨PENDIENTE⟩ |

**Propósito.** Automatiza (RPA) la interacción con el Portal de Correspondencia
y PQRSD de la Alcaldía de Floridablanca (Suite Neptuno), que no expone una API
oficial. El microservicio replica las peticiones del formulario web y ofrece
tres capacidades sobre HTTP/JSON:

1. Obtener los catálogos y listas desplegables del portal.
2. Consultar el estado, anexos y trazabilidad de un radicado existente.
3. Radicar una nueva PQRSD, anónima o identificada, con anexos.

**Dependencia externa crítica.** El portal
`portal.floridablanca.suiteneptuno.com` es un sistema de terceros sobre el que
NEXURA no tiene control ni SLA. Cualquier cambio en su HTML o en sus handlers
puede degradar el servicio; ver sección 8.

---

## 2. Arquitectura

| Elemento | Valor |
|---|---|
| Runtime | FastAPI (Python 3.12) sobre Cloud Run |
| Proyecto GCP (QAM) | ⟨PENDIENTE⟩ |
| Proyecto GCP (PREM) | ⟨PENDIENTE⟩ |
| Proyecto GCP (PROD) | ⟨PENDIENTE⟩ |
| Región | ⟨PENDIENTE — `cloudbuild.yaml` trae `us-central1` como valor por defecto⟩ |
| Servicio Cloud Run | `qam-rpa-pqrsd` / `prem-rpa-pqrsd` / `prod-rpa-pqrsd` |
| Imagen | `REGION-docker.pkg.dev/PROJECT/cloud-run/rpa-pqrsd:COMMIT_SHA` |
| Gateway | ⟨PENDIENTE⟩, path `/rpa/pqrsd/...` |
| Base de datos | Ninguna |
| VPC Connector | No requiere (solo tráfico saliente a internet público) |

**Flujo.**

```
Cliente → API Gateway (ESPv2) → Cloud Run (prod-rpa-pqrsd)
                                      ↓ HTTPS
                        portal.floridablanca.suiteneptuno.com
```

El servicio es sin estado salvo por una caché en memoria de catálogos
(TTL `CATALOGOS_CACHE_TTL_SECONDS`, por instancia). No requiere afinidad de
sesión ni almacenamiento persistente.

---

## 3. Endpoints

Contrato completo en [`openapi/openapi.yaml`](../openapi/openapi.yaml).

| Método | Path (Cloud Run) | Path (Gateway) | operationId | Auth | Descripción |
|---|---|---|---|---|---|
| GET | `/health` | `/rpa/pqrsd/health` | `getHealth` | No | Liveness. Devuelve `{"status":"UP"}` |
| GET | `/version` | `/rpa/pqrsd/version` | `getVersion` | No | Servicio, versión y ambiente |
| GET | `/v1/pqrsd/catalogos` | `/rpa/pqrsd/v1/catalogos` | `obtenerCatalogosPqrsd` | Sí | Catálogos del portal (cacheados) |
| POST | `/v1/pqrsd/consultar` | `/rpa/pqrsd/v1/consultar` | `consultarPqrsd` | Sí | Consulta por radicado + código |
| POST | `/v1/pqrsd/crear` | `/rpa/pqrsd/v1/crear` | `crearPqrsd` | Sí | Radica una PQRSD (multipart) |

**Códigos de respuesta.**

| Código | Significado |
|---|---|
| 200 | Procesado. En `/consultar`, `found:false` indica que el radicado no existe |
| 413 | Los anexos superan `MAX_UPLOAD_FILES`, `MAX_UPLOAD_BYTES` o `MAX_UPLOAD_TOTAL_BYTES` |
| 422 | Validación de entrada |
| 500 | Error interno; la respuesta incluye `correlation_id` para rastreo |
| 502 | El portal Neptuno no respondió o respondió algo no interpretable |

Toda respuesta incluye el header `X-Correlation-ID`.

---

## 4. Variables de entorno y secretos

**Este servicio no maneja credenciales: no tiene entradas en Secret Manager.**
El portal consultado es público y no exige autenticación. Si eso cambia, la
credencial debe ir a Secret Manager y montarse con `--set-secrets`, nunca como
variable de entorno plana.

| Variable | Tipo | Origen | Descripción |
|---|---|---|---|
| `SERVICE_NAME` | Configuración | env var | Nombre del servicio en `/version` y logs |
| `SERVICE_VERSION` | Configuración | env var | Commit SHA desplegado |
| `ENVIRONMENT` | Configuración | env var | `dev` / `qa` / `preprod` / `prod` |
| `LOG_LEVEL` | Configuración | env var | Nivel de log |
| `GOOGLE_CLOUD_PROJECT` | Configuración | env var | Necesario para correlacionar traces |
| `PORTAL_CONSULTA_URL` | Configuración | env var | Vista de consulta del portal |
| `PORTAL_RADICACION_URL` | Configuración | env var | Vista de radicación y catálogos |
| `PORTAL_USER_AGENT` | Configuración | default en código | Contiene comas; ver `docs/DEPLOY.md` |
| `HTTP_TIMEOUT_SECONDS` | Configuración | env var | Timeout por petición al portal |
| `HTTP_CONNECT_TIMEOUT_SECONDS` | Configuración | env var | Timeout de conexión |
| `HTTP_MAX_RETRIES` | Configuración | env var | Reintentos solo para GET idempotentes |
| `HTTP_MAX_CONNECTIONS` | Configuración | env var | Pool de conexiones salientes |
| `HTTP_MAX_KEEPALIVE_CONNECTIONS` | Configuración | env var | Conexiones keep-alive |
| `CATALOGOS_CACHE_TTL_SECONDS` | Configuración | env var | TTL de la caché de catálogos |
| `MAX_UPLOAD_FILES` | Configuración | env var | Anexos por radicación |
| `MAX_UPLOAD_BYTES` | Configuración | env var | Tamaño máximo por anexo |
| `MAX_UPLOAD_TOTAL_BYTES` | Configuración | env var | Tamaño máximo acumulado |
| `CORS_ALLOW_ORIGINS` | Configuración | env var | Vacío detrás del gateway |
| `EXPOSE_RAW_RESPONSE` | Configuración | env var | **Siempre `false` fuera de dev** |

Plantilla completa con comentarios en [`.env.example`](../.env.example).

---

## 5. Identidad y permisos IAM

| Rol | Service Account | Permisos |
|---|---|---|
| Ejecución (`run-sa`) | ⟨PENDIENTE⟩ | Ninguno adicional: no accede a otros servicios GCP |
| Despliegue (`deploy-sa`) | ⟨PENDIENTE⟩ | `roles/run.admin`, `roles/artifactregistry.writer`, `roles/iam.serviceAccountUser` |
| Invocación (gateway) | ⟨PENDIENTE⟩ | `roles/run.invoker` sobre el servicio |

El `run-sa` de este servicio no necesita `roles/secretmanager.secretAccessor`
porque no consume secretos.

---

## 6. Configuración de Cloud Run por ambiente

| Parámetro | QAM | PREM | PROD | Justificación |
|---|---|---|---|---|
| Rama Git | `dev` / `qa` | `master` | `main` | Estándar NEXURA |
| min-instances | 0 | 1 | 1 | Evitar cold start en ambientes con tráfico real |
| max-instances | 10 | 10 | 10 | Techo de carga sobre el portal de la Alcaldía |
| CPU | 1 | 1 | 1 | Carga dominada por espera de red, no por cómputo |
| Memoria | 512Mi | 512Mi | 512Mi | Suficiente con los límites de anexos vigentes |
| Concurrencia | 40 | 40 | 40 | Servicio asíncrono; limita presión sobre el portal |
| Timeout | 120 s | 120 s | 120 s | Cubre la radicación con anexos |
| Ingress | `all` | `internal-and-cloud-load-balancing` | `internal-and-cloud-load-balancing` | QAM permite prueba directa |
| Autenticación | `--no-allow-unauthenticated` en los tres | | | Radica trámites reales |

---

## 7. Observabilidad

**Logs.** JSON estructurado a stdout, campo `severity`, `correlation_id` en cada
línea y `logging.googleapis.com/trace` cuando hay trace context.

Filtro base en Cloud Logging:

```
resource.type="cloud_run_revision"
resource.labels.service_name="prod-rpa-pqrsd"
```

Seguir un request concreto de punta a punta:

```
resource.type="cloud_run_revision"
resource.labels.service_name="prod-rpa-pqrsd"
jsonPayload.correlation_id="<X-Correlation-ID de la respuesta>"
```

Fallos del portal externo:

```
resource.type="cloud_run_revision"
resource.labels.service_name="prod-rpa-pqrsd"
jsonPayload.message=~"portal_reintento|catalogos_portal_inaccesible|radicacion_fallida"
```

**Eventos de negocio emitidos.**

| Evento | Severidad | Cuándo |
|---|---|---|
| `request_completed` | INFO | Cada request (DEBUG para `/health` y `/version`) |
| `consulta_exitosa` | INFO | Consulta resuelta con datos |
| `radicacion_exitosa` | INFO | Radicado generado; incluye el número |
| `portal_reintento` | WARNING | Reintento de un GET al portal |
| `catalogo_no_disponible` | WARNING | Un catálogo no respondió |
| `seccion_no_disponible` | WARNING | Anexos o flujo no disponibles |
| `catalogos_portal_inaccesible` | ERROR | El portal no responde |
| `radicacion_fallida` | ERROR | Fallo de comunicación al radicar |
| `unhandled_exception` | ERROR | Excepción no controlada |

**Alertas sugeridas.** ⟨PENDIENTE de crear⟩

- Tasa de 502 > 5 % en 5 minutos → el portal está caído.
- `radicacion_fallida` > 0 en 5 minutos → radicaciones perdidas.
- Latencia p95 de `/v1/pqrsd/crear` > 60 s.

**Dashboard.** ⟨PENDIENTE — enlace de Cloud Monitoring⟩

---

## 8. Troubleshooting

| Síntoma | Causa probable | Acción |
|---|---|---|
| 401 en el gateway | Audience incorrecto: debe ser la URL del **gateway**, no la del Cloud Run | Revisar `x-google-audiences` en `gateway/gateway.yaml` |
| 403 desde el gateway al backend | Falta `roles/run.invoker` para la SA del gateway | Ver paso 2 de `docs/DEPLOY.md`, Modo B |
| 502 constante | Portal Neptuno caído o en mantenimiento | Confirmar el portal en el navegador; el servicio no puede compensarlo |
| 502 con `No se pudo extraer el token` | El portal cambió el HTML del formulario | Revisar `_extraer_token` en `api/services/pqrsd_service.py` |
| Catálogos vacíos con `success:true` | Handlers del portal caídos individualmente | El campo `message` lista cuáles fallaron |
| Catálogos desactualizados | Caché en memoria vigente | Llamar `/v1/pqrsd/catalogos?refrescar=true` |
| 413 al radicar | Anexos sobre el límite | Ajustar `MAX_UPLOAD_*` o reducir los anexos |
| Cold start lento en QAM | `min-instances=0` | Esperado; subir a 1 si molesta |
| Logs en texto plano | `setup_logging()` no corrió antes de FastAPI | Verificar el orden en `api/main.py` |
| Timeout del gateway antes que el servicio | `deadline` por debajo del tiempo del portal | Subir `deadline` en `gateway/gateway.yaml` |

**Duplicidad de radicados.** La radicación (`GenerarRadicado`) **no se
reintenta** de forma automática: un reenvío crearía un segundo trámite real en
la Alcaldía. Si `/v1/pqrsd/crear` devuelve 502, hay que verificar en el portal
si el radicado quedó creado **antes** de reintentar.

---

## 9. Checklist de cumplimiento GOB-GCP-STD-01

| Ítem | Estado |
|---|---|
| Código bajo `/api/` | ✅ |
| `api/core/config.py` con `pydantic-settings` y `@lru_cache` | ✅ |
| `api/core/logging.py` con JSON y campo `severity` | ✅ |
| `api/core/middleware.py` con `CorrelationMiddleware` | ✅ |
| `setup_logging()` antes de instanciar FastAPI | ✅ |
| `X-Correlation-ID` generado, propagado y devuelto | ✅ |
| `logging.googleapis.com/trace` inyectado | ✅ |
| `/health` y `/version` sin prefijo de versión | ✅ |
| Endpoints de negocio bajo `/v1` | ✅ |
| Dockerfile multi-stage, no-root, respeta `$PORT` | ✅ |
| `.dockerignore` excluye `.env`, `tests/`, `.git` | ✅ |
| `.env.example` sin credenciales reales | ✅ |
| `requirements.txt` con versiones fijas, sin deps de dev | ✅ |
| `requirements-dev.txt` | ✅ |
| `tests/` con health, version y correlation-id | ✅ |
| `openapi/openapi.yaml` exportado | ✅ |
| `scripts/export_openapi.py` | ✅ |
| `cloudbuild.yaml` con `$COMMIT_SHA` y sustituciones | ✅ |
| `azure-pipelines.yml` | ➖ Gestionado fuera de este repositorio |
| Ingress `internal-and-cloud-load-balancing` en PROD | ✅ Configurado; pendiente de aplicar en el despliegue |
| Secretos en Secret Manager | ➖ No aplica: el servicio no usa credenciales |
| `docs/MANUAL.md` completo | ⚠️ Pendiente de los campos ⟨PENDIENTE⟩ |

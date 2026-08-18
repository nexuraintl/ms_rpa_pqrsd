# Despliegue en Cloud Run — ms_rpa_pqrsd

Dos modos de exposición, ambos desde el mismo `cloudbuild.yaml`. Lo único que
cambia es la sustitución `_INGRESS`.

| Modo | `_INGRESS` | Uso | Autenticación |
|---|---|---|---|
| **A — Cloud Run directo** | `all` | Pruebas y validación funcional | Token de identidad de Google |
| **B — API Gateway** | `internal-and-cloud-load-balancing` | Producción | JWT de service account vía ESPv2 |

> El estándar de gobernanza (GOB-GCP-GOB-01) exige
> `internal-and-cloud-load-balancing` en producción. `all` solo es aceptable en
> ambientes de prueba y queda registrado como excepción.

---

## 0. Prerrequisitos (una sola vez por proyecto)

```bash
gcloud services enable run.googleapis.com cloudbuild.googleapis.com \
  artifactregistry.googleapis.com apigateway.googleapis.com \
  servicemanagement.googleapis.com servicecontrol.googleapis.com \
  --project="$PROJECT_ID"
```

Repositorio de imágenes:

```bash
gcloud artifacts repositories create cloud-run \
  --repository-format=docker --location="$REGION" --project="$PROJECT_ID"
```

Service account de ejecución (`run-sa`). Este servicio no lee secretos ni bases
de datos, así que no requiere roles adicionales más allá de los básicos:

```bash
gcloud iam service-accounts create run-rpa-pqrsd \
  --display-name="Cloud Run - rpa-pqrsd" --project="$PROJECT_ID"
```

---

## Modo A — Cloud Run directo (pruebas)

### Desplegar

```bash
gcloud builds submit --config=cloudbuild.yaml \
  --substitutions=_INGRESS=all,_SERVICE_PREFIX=qam,_ENVIRONMENT=qa,_REGION="$REGION",_RUN_SA="run-rpa-pqrsd@$PROJECT_ID.iam.gserviceaccount.com" \
  --project="$PROJECT_ID"
```

El servicio queda con `--no-allow-unauthenticated`: alcanzable desde internet
pero exigiendo un token válido. **No lo abras al público**: radica PQRSD reales
en el portal de la Alcaldía, y sin autenticación cualquiera podría generar
radicaciones masivas.

### Probar

```bash
SERVICE_URL=$(gcloud run services describe qam-rpa-pqrsd \
  --region="$REGION" --project="$PROJECT_ID" --format='value(status.url)')
```

```bash
curl -H "Authorization: Bearer $(gcloud auth print-identity-token)" "$SERVICE_URL/health"
```

```bash
curl -H "Authorization: Bearer $(gcloud auth print-identity-token)" "$SERVICE_URL/v1/pqrsd/catalogos"
```

```bash
curl -X POST "$SERVICE_URL/v1/pqrsd/consultar" \
  -H "Authorization: Bearer $(gcloud auth print-identity-token)" \
  -H "Content-Type: application/json" \
  -d '{"radicado":"2026488450","codigo_autenticacion":"202UhXbRIu2026488450"}'
```

Dar acceso a otra persona o sistema sin abrir el servicio:

```bash
gcloud run services add-iam-policy-binding qam-rpa-pqrsd \
  --region="$REGION" --project="$PROJECT_ID" \
  --member="user:persona@nexura.com" --role="roles/run.invoker"
```

---

## Modo B — API Gateway (producción)

### 1. Desplegar el Cloud Run cerrado

```bash
gcloud builds submit --config=cloudbuild.yaml \
  --substitutions=_INGRESS=internal-and-cloud-load-balancing,_SERVICE_PREFIX=prod,_ENVIRONMENT=prod,_REGION="$REGION",_MIN_INSTANCES=1,_RUN_SA="run-rpa-pqrsd@$PROJECT_ID.iam.gserviceaccount.com" \
  --project="$PROJECT_ID"
```

### 2. Permitir que el gateway invoque el servicio

```bash
gcloud run services add-iam-policy-binding prod-rpa-pqrsd \
  --region="$REGION" --project="$PROJECT_ID" \
  --member="serviceAccount:$GATEWAY_SA" --role="roles/run.invoker"
```

### 3. Preparar la configuración del gateway

`gateway/gateway.yaml` trae marcadores que deben reemplazarse antes de subirlo:

| Marcador | Valor |
|---|---|
| `__CLOUD_RUN_URL__` | URL del Cloud Run, **sin barra final** |
| `__GATEWAY_HOST__` | host del gateway del ambiente |
| `__CALLER_SA__` | service account que consume la API |

```bash
CLOUD_RUN_URL=$(gcloud run services describe prod-rpa-pqrsd \
  --region="$REGION" --project="$PROJECT_ID" --format='value(status.url)')
```

```bash
sed -e "s|__CLOUD_RUN_URL__|$CLOUD_RUN_URL|g" \
    -e "s|__GATEWAY_HOST__|$GATEWAY_HOST|g" \
    -e "s|__CALLER_SA__|$CALLER_SA|g" \
    gateway/gateway.yaml > /tmp/gateway-resuelto.yaml
```

### 4. Publicar la configuración

```bash
gcloud api-gateway api-configs create rpa-pqrsd-$(date +%Y%m%d-%H%M) \
  --api=nexura-gateway --openapi-spec=/tmp/gateway-resuelto.yaml \
  --backend-auth-service-account="$GATEWAY_SA" --project="$PROJECT_ID"
```

```bash
gcloud api-gateway gateways update nexura-gateway \
  --api=nexura-gateway --api-config=rpa-pqrsd-YYYYMMDD-HHMM \
  --location="$REGION" --project="$PROJECT_ID"
```

### 5. Verificar

```bash
curl -H "Authorization: Bearer $JWT" "https://$GATEWAY_HOST/rpa/pqrsd/health"
```

Rutas expuestas por el gateway:

| Gateway | Cloud Run | Autenticación |
|---|---|---|
| `GET /rpa/pqrsd/health` | `/health` | No |
| `GET /rpa/pqrsd/version` | `/version` | No |
| `GET /rpa/pqrsd/v1/catalogos` | `/v1/pqrsd/catalogos` | Sí |
| `POST /rpa/pqrsd/v1/consultar` | `/v1/pqrsd/consultar` | Sí |
| `POST /rpa/pqrsd/v1/crear` | `/v1/pqrsd/crear` | Sí |

---

## Cambiar de modo sin reconstruir

El ingress se modifica en caliente sobre el servicio ya desplegado:

```bash
gcloud run services update prod-rpa-pqrsd --region="$REGION" \
  --ingress=internal-and-cloud-load-balancing --project="$PROJECT_ID"
```

---

## Rollback

```bash
gcloud run revisions list --service=prod-rpa-pqrsd --region="$REGION" --project="$PROJECT_ID"
```

```bash
gcloud run services update-traffic prod-rpa-pqrsd \
  --to-revisions=REVISION_ANTERIOR=100 --region="$REGION" --project="$PROJECT_ID"
```

---

## Notas de operación

**Comas en `--set-env-vars`.** `PORTAL_USER_AGENT` contiene comas
(`(KHTML, like Gecko)`) y rompería el parseo de `gcloud`. Por eso el
`cloudbuild.yaml` no la envía y el valor por defecto vive en
`api/core/config.py`. Si hay que sobrescribirla, usar delimitador alterno:

```bash
gcloud run services update prod-rpa-pqrsd --region="$REGION" \
  --set-env-vars="^@^PORTAL_USER_AGENT=Mozilla/5.0 (KHTML, like Gecko) Chrome/120"
```

**`EXPOSE_RAW_RESPONSE` debe quedar en `false`.** Incluye en la respuesta el
payload completo del portal, con datos personales del ciudadano. El
`cloudbuild.yaml` lo fuerza a `false` en cada despliegue.

**Concurrencia.** El servicio es asíncrono y su trabajo es esperar al portal
externo, no consumir CPU. `--concurrency=40` con 1 vCPU es un punto de partida
razonable; subirlo aumenta la carga sobre el portal de la Alcaldía, que es un
sistema de terceros.

**Timeouts.** El `deadline` del gateway debe ser mayor que el tiempo del portal.
Los valores en `gateway/gateway.yaml` (60 s consulta, 120 s radicación) están
por encima de `HTTP_TIMEOUT_SECONDS=30` con margen para reintentos.

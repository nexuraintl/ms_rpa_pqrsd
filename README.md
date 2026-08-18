# ms_rpa_pqrsd — Microservicio RPA PQRSD (Alcaldía de Floridablanca)

Microservicio **FastAPI sobre Cloud Run** que automatiza la interacción con el
Portal de Correspondencia y PQRSD de la Alcaldía de Floridablanca (Suite
Neptuno), que no expone una API oficial.

Cumple el estándar de Gobernanza GCP de NEXURA **GOB-GCP-STD-01**.

---

## Funcionalidades

| Endpoint | Método | Descripción |
|---|---|---|
| `/v1/pqrsd/catalogos` | GET | Tipos de PQRSD, dependencias y listas de caracterización |
| `/v1/pqrsd/consultar` | POST | Estado, datos, anexos y flujo de un radicado |
| `/v1/pqrsd/crear` | POST | Radica una PQRSD (anónima o identificada, con anexos) |
| `/health` | GET | Liveness |
| `/version` | GET | Servicio, versión y ambiente |

Detalle de integración para clientes y agentes: [`AGENT_GUIDE.md`](AGENT_GUIDE.md).

---

## Estructura

```
api/
├── main.py                setup y registro de routers
├── core/
│   ├── config.py          pydantic-settings + get_settings() cacheado
│   ├── logging.py         JSON a stdout con severity y trace
│   └── middleware.py      Correlation-ID y trace context
├── models/schemas.py      contratos Pydantic
├── routers/
│   ├── health.py          /health y /version (sin /v1)
│   └── v1/pqrsd.py        endpoints de negocio
└── services/pqrsd_service.py   cliente httpx del portal Neptuno

docs/MANUAL.md             manual operativo (GOB-GCP-STD-01)
docs/DEPLOY.md             despliegue: Cloud Run directo y API Gateway
gateway/gateway.yaml       ficha ESPv2 para el API Gateway
openapi/openapi.yaml       contrato exportado
cloudbuild.yaml            build y deploy
```

---

## Desarrollo local

```bash
python -m venv .venv && .venv/Scripts/Activate.ps1
```

```bash
pip install -r requirements-dev.txt
```

```bash
cp .env.example .env
```

```bash
uvicorn api.main:app --reload --port 8000
```

Swagger UI en <http://localhost:8000/docs>.

### Pruebas

```bash
pytest
```

Ninguna prueba sale a la red: el portal se simula con `httpx.MockTransport`.

### Regenerar el contrato OpenAPI

```bash
python scripts/export_openapi.py
```

---

## Docker

```bash
docker build -t rpa-pqrsd .
```

```bash
docker run --rm -p 8080:8080 --env-file .env rpa-pqrsd
```

La imagen respeta `$PORT` y corre como usuario sin privilegios.

---

## Despliegue

Ver [`docs/DEPLOY.md`](docs/DEPLOY.md). Dos modos desde el mismo pipeline:

- **Cloud Run directo** (`_INGRESS=all`) para pruebas.
- **API Gateway** (`_INGRESS=internal-and-cloud-load-balancing`) para producción.

---

## Advertencia operativa

Este servicio **radica trámites reales** en el portal de la Alcaldía. La
radicación no se reintenta automáticamente y el servicio nunca debe desplegarse
con `--allow-unauthenticated`.

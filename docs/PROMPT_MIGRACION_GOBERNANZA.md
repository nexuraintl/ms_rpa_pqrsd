# Prompt reutilizable — migrar un microservicio al estándar GOB-GCP-STD-01

Pegar en una sesión nueva de Claude Code, **parado en la raíz del repositorio**
del microservicio. Rellenar el bloque "Datos del servicio" antes de enviar.

Derivado de la migración real de `ms_rpa_pqrsd` (agosto 2026). La sección de
trampas es lo que costó tiempo esa vez: no es teórica.

---

## El prompt

Necesito dejar este microservicio FastAPI listo para producción en Cloud Run,
cumpliendo el estándar de Gobernanza GCP de NEXURA.

### Paso 1 — instala la skill (no viene incluida)

Descárgala y guárdala en `.claude/skills/gobernanza-gcp-code/SKILL.md`:

    https://raw.githubusercontent.com/nexuraintl/nexura_claude_skills/main/gobernanza-gcp-code/SKILL.md

Bájala con `curl` y léela con Read. No uses WebFetch para eso: devuelve un
resumen en vez del texto literal y te vas a perder los checklists.

### Paso 2 — ejecuta la skill completa

Fase 1: análisis estructural y de contenido, con el reporte en el formato que
define la skill. Fase 2: aplica las correcciones. Preséntame el reporte antes
de tocar código.

### Datos del servicio

- Módulo: `<rellenar>`
- Microservicio: `<rellenar>`
- Proyecto GCP (QAM / PREM / PROD): `<rellenar>`
- Región: `<rellenar>`
- run-sa: `<rellenar>`
- deploy-sa: `<rellenar>`
- Base de datos (Mongo / MySQL / ninguna): `<rellenar>`
- ¿Se expone por API Gateway ESPv2?: `<sí / no / ambos>`
- ¿Ya existe `.azure-pipelines.yml` en el repo?: `<sí / no>`

Si algo de esto queda sin definir, pregúntamelo antes de la Fase 2 en vez de
inventarlo. En `docs/MANUAL.md` marca como PENDIENTE lo que solo el equipo
puede saber (responsables, proyectos de otros ambientes, host del gateway).

### Convenciones NEXURA — no las deduzcas

- Repositorio: `ms_[módulo]_[microservicio]`
- Servicio Cloud Run: `[qam|prem|prod]-[módulo]-[microservicio]`
- Path en el gateway: `/[módulo]/[microservicio]/v1/...`
- Ambientes: QAM ← ramas `dev`/`qa` · PREM ← `master` · PROD ← `main`
- min-instances: 0 en QAM, 1 en PREM y PROD
- Negocio bajo `/v1/`; `/health` y `/version` sin prefijo y sin autenticación
- Trigger de Cloud Build: `trigger-[ambiente]-[módulo]-[servicio]`, apuntando a
  `cloudbuild.yaml` y con conexión de repositorio de **2ª generación**
- Ingress: `internal-and-cloud-load-balancing` en producción, nunca `all`
- Secretos: solo Secret Manager, jamás en variables de entorno planas

### Trampas verificadas — revísalas una por una y dime cómo quedó cada una

**Dependencias**

1. Si el servicio usa `Form(...)` o `UploadFile`, declara `python-multipart` en
   `requirements.txt`. FastAPI lo exige pero no lo declara: sin él, registrar la
   ruta lanza RuntimeError al importar la app, el proceso muere antes de
   escuchar en `$PORT` y Cloud Run solo dice "container failed to start".
2. No confíes en que los tests pasen: el virtualenv de desarrollo suele tener
   paquetes que `requirements.txt` no declara. Verifica instalando **únicamente**
   `requirements.txt` en un directorio limpio y corriendo la suite ahí.
3. Elimina dependencias declaradas y no usadas.
4. Versiones fijas (`==`), no rangos.

**Cliente HTTP**

5. Si migras de `requests` a `httpx`: httpx **reemplaza** el query string de la
   URL cuando pasas `params=`, mientras requests lo fusiona. Un
   `client.get("...?handler=X", params={...})` pierde el `handler` en silencio.
6. httpx no sigue redirecciones por defecto; requests sí. Usa
   `follow_redirects=True` si replicas su comportamiento.
7. Nunca hagas I/O bloqueante dentro de un handler `async def`: congela el event
   loop y anula la concurrencia del contenedor.
8. Peticiones que **crean registros** no se reintentan nunca. Un reintento
   duplica el registro. Reintenta solo GET idempotentes.
9. Llamadas independientes van en paralelo con `asyncio.gather`, no en serie: N
   llamadas secuenciales con timeout de 30 s se comen el timeout del request.

**Cloud Build**

10. `options.logging: CLOUD_LOGGING_ONLY` es obligatorio cuando el build corre
    con service account propia; sin eso el build falla al arrancar.
11. `$COMMIT_SHA` solo se llena en builds disparados por trigger. En un
    `gcloud builds submit` manual llega vacío y el tag de la imagen sale
    inválido: pásalo con `--substitutions=COMMIT_SHA=$(git rev-parse --short HEAD)`.
12. Pon el paso de tests **primero**. Es lo único que evita desplegar una imagen
    que no arranca, y corre en un contenedor limpio, así que detecta las
    dependencias faltantes del punto 1.
13. La implementación continua integrada de Cloud Run **ignora el
    `cloudbuild.yaml`**: construye el Dockerfile directo, sin tests ni variables
    de entorno. Usa un trigger propio contra `cloudbuild.yaml`.

**Cloud Run**

14. Valores con comas rompen `--set-env-vars`. Deja el default en el código o usa
    el delimitador alterno `^@^`.
15. Con `_INGRESS=internal-and-cloud-load-balancing` el servicio **no es
    alcanzable** desde Postman ni desde tu máquina: da 404 del Google Front End.
16. Despliega siempre con `--no-allow-unauthenticated`. Para probar,
    `gcloud auth print-identity-token` (identity token, no access token).
17. El `audience` del token debe ser la URL exacta del servicio, sin barra final.
18. `max-instances=1` serializa todo y provoca 429 durante los despliegues.
19. `--timeout-keep-alive` mayor que el idle del balanceador (600 s) evita 502
    por reutilización de conexiones.
20. Dockerfile: multi-stage, usuario no-root, `${PORT:-8080}`, arranque con
    `uvicorn api.main:app` (no `python api/main.py`).

**Aplicación**

21. No combines `allow_origins=["*"]` con `allow_credentials=True`: el navegador
    lo rechaza. Haz CORS configurable y déjalo vacío detrás del gateway.
22. Limita tamaño y cantidad de archivos subidos, leyéndolos por trozos. Un
    upload sin tope agota la memoria de la instancia.
23. No devuelvas payloads crudos de sistemas externos: suelen traer datos
    personales. Ponlo detrás de un flag que quede en `false`.
24. Resolver la configuración a nivel de módulo hace que cualquier variable de
    entorno mal puesta tumbe el arranque. Es un compromiso consciente: decídelo
    y déjalo dicho.
25. `HTTP_413_REQUEST_ENTITY_TOO_LARGE` y `HTTP_422_UNPROCESSABLE_ENTITY` están
    deprecados en Starlette reciente: usa `HTTP_413_CONTENT_TOO_LARGE` y
    `HTTP_422_UNPROCESSABLE_CONTENT`.
26. Los tests no deben tocar la red. Simula el sistema externo con
    `httpx.MockTransport` e inyecta el transport en el servicio.

**Git y CI**

27. Si el repo tiene remoto de Azure DevOps, revisa si la URL trae un PAT
    incrustado en `.git/config`. Avísame en vez de imprimirlo.
28. Con el bridge ADO→GitHub, **Azure es la fuente de verdad**: el pipeline
    sincroniza con `git push --force` y borra lo que se haya commiteado directo
    en GitHub.
29. La rama por defecto del espejo puede tener código viejo. El trigger debe
    apuntar a la rama del ambiente, no a la rama por defecto.

### Entregables

Además de lo que exige la skill, quiero:

- `docs/DEPLOY.md` con los comandos concretos de cada modo de exposición
- `gateway/gateway.yaml` con los marcadores a reemplazar, si aplica gateway
- `openapi/openapi.yaml` regenerado, con `operationId` únicos
- La suite de tests corriendo y verificada contra dependencias limpias
- Un reporte final de verificación post-corrección, con lo que quedó pendiente

No hagas commit ni push hasta que yo lo pida.

---

## Notas de uso

- El paso 1 es necesario porque la skill vive en un repositorio aparte y no se
  instala sola. Una vez guardada en `.claude/skills/`, queda disponible para
  todo el equipo si se commitea.
- Si el repositorio ya cumple parcialmente el estándar, la skill lo detecta como
  repo NUEVO y el reporte sale mucho más corto. El prompt sirve igual.
- La lista de trampas conviene ampliarla cada vez que una migración descubra una
  nueva. Es la parte que no está en el estándar, y es la que evita repetir el
  mismo día de depuración.

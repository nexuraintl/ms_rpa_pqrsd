"""Exporta el contrato OpenAPI del servicio a openapi/openapi.yaml.

Uso (desde la raíz del repositorio):
    python scripts/export_openapi.py

Regenerar y commitear el contrato cada vez que cambie un endpoint: es la
fuente que consume la ficha del API Gateway y la sección 3 del MANUAL.
"""

import pathlib
import sys

RAIZ = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))

import yaml  # noqa: E402

from api.main import app  # noqa: E402

DESTINO = RAIZ / "openapi" / "openapi.yaml"


def main() -> None:
    especificacion = app.openapi()

    DESTINO.parent.mkdir(parents=True, exist_ok=True)
    DESTINO.write_text(
        yaml.safe_dump(especificacion, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )

    rutas = len(especificacion.get("paths", {}))
    print(f"Contrato exportado a {DESTINO.relative_to(RAIZ)} ({rutas} rutas)")


if __name__ == "__main__":
    main()

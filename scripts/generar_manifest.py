from __future__ import annotations

import csv
import hashlib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "MANIFEST.csv"

DIRECTORIOS_EXCLUIDOS = {
    ".git",
    ".ipynb_checkpoints",
    ".jupyter",
    "__pycache__",
}
RUTAS_EXCLUIDAS = {
    Path("build"),
    Path("figuras/comparacion_clasica.png"),
    Path("figuras/originales"),
    Path("resultados/qir"),
}
ARCHIVOS_EXCLUIDOS = {
    ".DS_Store",
    "MANIFEST.csv",
    "MANIFEST.csv.tmp",
}


def archivo_de_entrega(ruta: Path) -> bool:
    relativa = ruta.relative_to(ROOT)
    if not ruta.is_file() or ruta.name in ARCHIVOS_EXCLUIDOS:
        return False
    if any(parte in DIRECTORIOS_EXCLUIDOS for parte in relativa.parts):
        return False
    return not any(
        relativa == excluida or excluida in relativa.parents
        for excluida in RUTAS_EXCLUIDAS
    )


def archivos_entrega() -> list[Path]:
    return sorted(
        (ruta for ruta in ROOT.rglob("*") if archivo_de_entrega(ruta)),
        key=lambda ruta: ruta.relative_to(ROOT).as_posix(),
    )


def sha256(ruta: Path) -> str:
    resumen = hashlib.sha256()
    with ruta.open("rb") as archivo:
        for bloque in iter(lambda: archivo.read(1024 * 1024), b""):
            resumen.update(bloque)
    return resumen.hexdigest()


def generar_manifest() -> None:
    temporal = MANIFEST.with_suffix(".csv.tmp")
    with temporal.open("w", encoding="utf-8", newline="") as archivo:
        escritor = csv.writer(archivo, lineterminator="\n")
        escritor.writerow(["ruta", "bytes", "sha256"])
        for ruta in archivos_entrega():
            escritor.writerow(
                [
                    ruta.relative_to(ROOT).as_posix(),
                    ruta.stat().st_size,
                    sha256(ruta),
                ]
            )
    temporal.replace(MANIFEST)


if __name__ == "__main__":
    generar_manifest()
    print(f"MANIFEST regenerado: {len(archivos_entrega())} archivos.")

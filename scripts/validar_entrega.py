from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

from generar_manifest import archivos_entrega


ROOT = Path(__file__).resolve().parents[1]
TAMANOS = (6, 8, 10, 12)

obligatorios = [
    ROOT / "README.md",
    ROOT / "requirements.txt",
    ROOT / "config.yaml",
    ROOT / "scripts" / "ejecutar_entrega.py",
    ROOT / "notebooks" / "reto1_final.ipynb",
    ROOT / "notebooks" / "04_seleneplus.ipynb",
    ROOT
    / "resultados"
    / "qaoa_local"
    / "resumen_mediciones_512_shots.csv",
    ROOT / "resultados" / "remoto" / "seleneplus_p3_resumen.csv",
]
for ruta in obligatorios:
    assert ruta.exists() and ruta.stat().st_size > 0, f"Falta: {ruta}"

with (ROOT / "MANIFEST.csv").open(encoding="utf-8", newline="") as archivo:
    filas_manifest = list(csv.DictReader(archivo))

rutas_manifest = {fila["ruta"] for fila in filas_manifest}
rutas_actuales = {
    ruta.relative_to(ROOT).as_posix()
    for ruta in archivos_entrega()
}
assert rutas_manifest == rutas_actuales, "MANIFEST no coincide con el paquete."

for fila in filas_manifest:
    ruta = ROOT / fila["ruta"]
    assert ruta.stat().st_size == int(fila["bytes"]), (
        f"Tamaño incorrecto en MANIFEST: {fila['ruta']}"
    )
    resumen = hashlib.sha256(ruta.read_bytes()).hexdigest()
    assert resumen == fila["sha256"], (
        f"Hash incorrecto en MANIFEST: {fila['ruta']}"
    )

for notebook in sorted((ROOT / "notebooks").glob("*.ipynb")):
    contenido = json.loads(notebook.read_text(encoding="utf-8"))
    assert contenido["nbformat"] == 4
    errores = [
        salida
        for celda in contenido["cells"]
        for salida in celda.get("outputs", [])
        if salida.get("output_type") == "error"
    ]
    assert not errores, f"{notebook.name} conserva errores ejecutados."

baseline = pd.read_csv(
    ROOT / "resultados" / "clasicos" / "baseline_clasico_completo.csv"
)
exactos = (
    baseline[baseline["metodo"].eq("Exacto")]
    .set_index("n")["optimo_exacto"]
    .to_dict()
)

for n in TAMANOS:
    nodos = pd.read_csv(
        ROOT / "datos" / "grafos" / f"grafo_{n}_nodos.csv"
    )
    aristas = pd.read_csv(
        ROOT / "datos" / "grafos" / f"grafo_{n}_aristas.csv"
    )
    assert len(nodos) == n
    assert len(aristas) == n - 1
    assert set(nodos["region"]) == {"Central"}
    assert (aristas["weight"] > 0).all()
    assert np.isclose(aristas["weight"].sum(), exactos[n], atol=1e-8)

qaoa = pd.read_csv(
    ROOT / "resultados" / "qaoa_local" / "resumen_mediciones_512_shots.csv"
)
assert len(qaoa) == 12
assert set(qaoa["n"]) == set(TAMANOS)
assert set(qaoa["p"]) == {1, 2, 3}
assert (qaoa["razon_muestral_std"] >= 0).all()
assert qaoa["razon_muestral_media"].between(0, 1).all()

selene = pd.read_csv(
    ROOT / "resultados" / "remoto" / "seleneplus_p3_resumen.csv"
)

columnas_selene_obligatorias = {
    "n",
    "p",
    "shots",
    "estado",
    "backend",
    "job_id",
    "razon_seleneplus",
}
columnas_selene_faltantes = columnas_selene_obligatorias - set(selene.columns)
assert not columnas_selene_faltantes, (
    "Faltan columnas obligatorias en seleneplus_p3_resumen.csv: "
    f"{sorted(columnas_selene_faltantes)}. "
    f"Columnas disponibles: {list(selene.columns)}"
)

assert len(selene) == 4, (
    f"Se esperaban 4 resultados SelenePlus y se encontraron {len(selene)}."
)
assert set(pd.to_numeric(selene["n"], errors="raise")) == set(TAMANOS), (
    f"Tamaños SelenePlus inesperados: {sorted(selene['n'].unique())}"
)
assert set(pd.to_numeric(selene["p"], errors="raise")) == {3}, (
    f"Profundidades SelenePlus inesperadas: {sorted(selene['p'].unique())}"
)
assert pd.to_numeric(selene["shots"], errors="raise").eq(512).all(), (
    f"Shots SelenePlus inesperados: {sorted(selene['shots'].unique())}"
)
estados_selene = selene["estado"].astype(str).str.strip().str.upper()
assert estados_selene.eq("COMPLETED").all(), (
    f"Estados SelenePlus inesperados: {sorted(estados_selene.unique())}"
)

backends_validos = {"SelenePlus", "SelenePlusConfig"}
backends_selene = selene["backend"].astype(str).str.strip()
assert backends_selene.isin(backends_validos).all(), (
    "Backend remoto inesperado: "
    f"{sorted(backends_selene.unique())}"
)

job_ids = selene["job_id"].astype(str).str.strip()
assert job_ids.ne("").all() and job_ids.str.lower().ne("nan").all(), (
    "El identificador del trabajo SelenePlus está vacío."
)
assert job_ids.nunique() == 1, (
    f"Se esperaba un único job de SelenePlus: {sorted(job_ids.unique())}"
)

razones_selene = pd.to_numeric(
    selene["razon_seleneplus"],
    errors="raise",
)
assert razones_selene.between(0, 1).all(), (
    "Hay razones SelenePlus fuera del intervalo [0, 1]: "
    f"{razones_selene[~razones_selene.between(0, 1)].tolist()}"
)

# El resumen nuevo identifica directamente el backend como SelenePlus y no
# necesita la columna heredada `es_h2_emulator`. Si una versión anterior del
# CSV todavía la incluye, comprobamos que todos sus valores sean falsos sin
# usar astype(bool), pues bool("False") es True en Python.
if "es_h2_emulator" in selene.columns:
    valores_booleanos = (
        selene["es_h2_emulator"]
        .astype(str)
        .str.strip()
        .str.lower()
    )
    falsos_validos = {"false", "0", "no", "n", ""}
    assert valores_booleanos.isin(falsos_validos).all(), (
        "El resumen declara una ejecución H2 Emulator: "
        f"{sorted(valores_booleanos.unique())}"
    )

print("Validación estructural y numérica: OK")
print("MANIFEST y contenido del paquete: OK")
print("Resultado SelenePlus: COMPLETED.")

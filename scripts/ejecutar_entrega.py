from __future__ import annotations

import argparse
import importlib.util
import shutil
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
NOTEBOOKS = ROOT / "notebooks"

NOTEBOOKS_LOCALES = [
    NOTEBOOKS / "00_entorno.ipynb",
    NOTEBOOKS / "01_validacion_grafos.ipynb",
    NOTEBOOKS / "02_qubo_baselines.ipynb",
    NOTEBOOKS / "03_qaoa_ideal_guppy.ipynb",
]
NOTEBOOK_SELENEPLUS = NOTEBOOKS / "04_seleneplus.ipynb"
NOTEBOOK_FINAL = NOTEBOOKS / "reto1_final.ipynb"
CONSTRUCTOR_GRAFOS = ROOT / "scripts" / "construir_grafo_ice.py"
BUILD_GRAFOS = ROOT / "build" / "grafos_ice"
GRAFOS_OFICIALES = ROOT / "datos" / "grafos"
TAMANOS_GRAFOS = (6, 8, 10, 12)

MODULOS_RESULTADOS = [
    "matplotlib",
    "numpy",
    "pandas",
]
MODULOS_COMPLETOS = [
    "IPython",
    "cvxpy",
    "guppylang",
    "ipykernel",
    "jupyter_client",
    "matplotlib",
    "nbclient",
    "nbformat",
    "networkx",
    "numpy",
    "pandas",
    "pyproj",
    "scipy",
    "seaborn",
    "shapely",
    "yaml",
]
MODULOS_SELENEPLUS = [
    "qnexus",
]


def verificar_modulos(modulos: list[str]) -> None:
    faltantes = [
        modulo
        for modulo in modulos
        if importlib.util.find_spec(modulo) is None
    ]
    if faltantes:
        lista = ", ".join(faltantes)
        raise RuntimeError(
            f"Faltan dependencias: {lista}. "
            "Ejecute: python -m pip install -r requirements.txt"
        )


def ejecutar_script(ruta: Path, argumentos: list[str] | None = None) -> None:
    print(f"\n>>> {ruta.relative_to(ROOT)}", flush=True)
    subprocess.run(
        [sys.executable, str(ruta), *(argumentos or [])],
        cwd=ROOT,
        check=True,
    )


def ejecutar_notebook(ruta: Path, timeout: int) -> None:
    import nbformat
    from nbclient import NotebookClient

    print(f"\n>>> {ruta.relative_to(ROOT)}", flush=True)
    notebook = nbformat.read(ruta, as_version=4)
    cliente = NotebookClient(
        notebook,
        timeout=timeout,
        kernel_name="python3",
        resources={"metadata": {"path": str(ruta.parent)}},
        allow_errors=False,
    )
    cliente.execute()
    nbformat.write(notebook, ruta)


def reconstruir_grafos() -> None:
    """Reconstruye y publica automáticamente la única copia oficial."""
    ejecutar_script(
        CONSTRUCTOR_GRAFOS,
        [
            "--project-root",
            str(ROOT),
            "--output-root",
            str(BUILD_GRAFOS),
            "--config",
            str(ROOT / "config.yaml"),
            "--offline",
        ],
    )

    origen = BUILD_GRAFOS / "datos" / "grafos"
    GRAFOS_OFICIALES.mkdir(parents=True, exist_ok=True)
    for n in TAMANOS_GRAFOS:
        for extension in ("graphml", "csv"):
            nombres = (
                [f"grafo_{n}.{extension}"]
                if extension == "graphml"
                else [
                    f"grafo_{n}_nodos.csv",
                    f"grafo_{n}_aristas.csv",
                ]
            )
            for nombre in nombres:
                fuente = origen / nombre
                if not fuente.is_file():
                    raise FileNotFoundError(
                        f"El constructor no generó el archivo esperado: {fuente}"
                    )
                shutil.copy2(fuente, GRAFOS_OFICIALES / nombre)

    print(
        "\n>>> Grafos reconstruidos y publicados en datos/grafos.",
        flush=True,
    )


def verificar_bloqueo_seleneplus() -> None:
    import ast
    import nbformat

    notebook = nbformat.read(NOTEBOOK_SELENEPLUS, as_version=4)
    asignaciones = []
    for celda in notebook.cells:
        if celda.cell_type != "code":
            continue
        arbol = ast.parse("".join(celda.get("source", "")))
        asignaciones.extend(
            nodo.value
            for nodo in ast.walk(arbol)
            if isinstance(nodo, ast.Assign)
            and any(
                isinstance(destino, ast.Name)
                and destino.id == "ENVIAR_NUEVO_JOB"
                for destino in nodo.targets
            )
        )

    bloqueo_valido = (
        len(asignaciones) == 1
        and isinstance(asignaciones[0], ast.Constant)
        and asignaciones[0].value is False
    )
    if not bloqueo_valido:
        raise RuntimeError(
            "Se canceló la recuperación: "
            "ENVIAR_NUEVO_JOB debe tener una única asignación literal a False."
        )


def finalizar() -> None:
    ejecutar_script(ROOT / "scripts" / "generar_manifest.py")
    ejecutar_script(ROOT / "scripts" / "validar_entrega.py")


def modo_resultados() -> None:
    verificar_modulos(MODULOS_RESULTADOS)
    ejecutar_script(ROOT / "scripts" / "generar_figuras.py")
    finalizar()


def modo_completo(timeout: int, recuperar_seleneplus: bool) -> None:
    modulos = MODULOS_COMPLETOS.copy()
    if recuperar_seleneplus:
        modulos.extend(MODULOS_SELENEPLUS)
    verificar_modulos(modulos)

    reconstruir_grafos()

    for notebook in NOTEBOOKS_LOCALES:
        ejecutar_notebook(notebook, timeout)

    if recuperar_seleneplus:
        verificar_bloqueo_seleneplus()
        ejecutar_notebook(NOTEBOOK_SELENEPLUS, timeout)
    else:
        print(
            "\n>>> SelenePlus no se recupera: "
            "se utiliza el resultado incluido en el paquete.",
            flush=True,
        )

    ejecutar_notebook(NOTEBOOK_FINAL, timeout)
    finalizar()


def crear_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Punto único de entrada para validar o reproducir "
            "la entrega del Challenge 1."
        )
    )
    parser.add_argument(
        "--modo",
        choices=("validar", "resultados", "completo"),
        default="resultados",
        help=(
            "validar: no recalcula; resultados: regenera figuras y tablas; "
            "completo: reejecuta el flujo local y regenera resultados."
        ),
    )
    parser.add_argument(
        "--recuperar-seleneplus",
        action="store_true",
        help=(
            "En modo completo, recupera el job existente. "
            "Nunca habilita el envío de un trabajo nuevo."
        ),
    )
    parser.add_argument(
        "--timeout-celda",
        type=int,
        default=1800,
        help="Tiempo máximo por celda de notebook, en segundos.",
    )
    return parser


def main() -> None:
    argumentos = crear_parser().parse_args()
    if argumentos.recuperar_seleneplus and argumentos.modo != "completo":
        raise SystemExit(
            "--recuperar-seleneplus solo puede usarse con --modo completo."
        )
    if argumentos.timeout_celda <= 0:
        raise SystemExit("--timeout-celda debe ser mayor que cero.")

    if argumentos.modo == "validar":
        ejecutar_script(ROOT / "scripts" / "validar_entrega.py")
    elif argumentos.modo == "resultados":
        modo_resultados()
    else:
        modo_completo(
            timeout=argumentos.timeout_celda,
            recuperar_seleneplus=argumentos.recuperar_seleneplus,
        )


if __name__ == "__main__":
    main()

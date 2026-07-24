from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
FIGURAS = ROOT / "figuras"
TABLAS = ROOT / "resultados" / "tablas_finales"
FIGURAS.mkdir(exist_ok=True)
TABLAS.mkdir(parents=True, exist_ok=True)

qaoa = pd.read_csv(
    ROOT / "resultados" / "qaoa_local" / "resumen_mediciones_512_shots.csv"
)
guppy = pd.read_csv(
    ROOT / "resultados" / "qaoa_local" / "resumen_12_configuraciones.csv"
)
reinicios = pd.read_csv(
    ROOT / "resultados" / "qaoa_local" / "optimizacion_todos_reinicios.csv"
)
clasicos = pd.read_csv(
    ROOT / "resultados" / "clasicos" / "baseline_clasico_completo.csv"
)
selene = pd.read_csv(
    ROOT / "resultados" / "remoto" / "seleneplus_p3_resumen.csv"
)

# El notebook SelenePlus exporta esta métrica como
# ``probabilidad_optimo``. Versiones anteriores del paquete utilizaban
# ``probabilidad_optimo_seleneplus`` y algunas salidas intermedias,
# ``probabilidad_optimo_pct``. Normalizamos el esquema aquí para que las
# figuras y tablas puedan regenerarse con cualquiera de esas versiones.
if "probabilidad_optimo_seleneplus" not in selene.columns:
    if "probabilidad_optimo" in selene.columns:
        selene["probabilidad_optimo_seleneplus"] = selene[
            "probabilidad_optimo"
        ]
    elif "probabilidad_optimo_pct" in selene.columns:
        selene["probabilidad_optimo_seleneplus"] = (
            selene["probabilidad_optimo_pct"] / 100.0
        )
    else:
        raise ValueError(
            "El resumen SelenePlus no contiene una columna de probabilidad "
            "del óptimo. Columnas disponibles: "
            f"{list(selene.columns)}"
        )

colores = {6: "#1f77b4", 8: "#ff7f0e", 10: "#2ca02c", 12: "#d62728"}


# 1. Calidad típica frente a profundidad.
fig, ax = plt.subplots(figsize=(10, 6))
for n in sorted(qaoa["n"].unique()):
    datos = qaoa[qaoa["n"].eq(n)].sort_values("p")
    ax.errorbar(
        datos["p"],
        datos["razon_muestral_media"],
        yerr=datos["razon_muestral_std"],
        marker="o",
        capsize=4,
        color=colores[n],
        label=f"G{n}: media de 30 × 512 tiros",
    )
    ax.plot(
        datos["p"],
        datos["razon_ideal"],
        "--",
        color=colores[n],
        alpha=0.65,
        label=f"G{n}: valor ideal",
    )
ax.set_xticks([1, 2, 3])
ax.set_ylim(0.74, 0.94)
ax.set_xlabel("Profundidad p")
ax.set_ylabel("Razón de aproximación esperada")
ax.set_title("Calidad típica de QAOA frente a profundidad")
ax.grid(alpha=0.25)
ax.legend(ncol=2, fontsize=8)
fig.tight_layout()
fig.savefig(FIGURAS / "01_calidad_media_vs_profundidad.png", dpi=240)
plt.close(fig)


# 2. Probabilidad por tiro, no la probabilidad saturada de ver al menos un
# óptimo dentro de un lote de 512 tiros.
fig, ax = plt.subplots(figsize=(10, 6))
for p in (1, 2, 3):
    datos = qaoa[qaoa["p"].eq(p)].sort_values("n")
    ax.semilogy(
        datos["n"],
        100 * datos["probabilidad_optimo_ideal"],
        marker="o",
        label=f"Ideal, p={p}",
    )
selene_ordenado = selene.sort_values("n")
ax.semilogy(
    selene_ordenado["n"],
    100 * selene_ordenado["probabilidad_optimo_seleneplus"],
    marker="D",
    linestyle="--",
    linewidth=2,
    color="#6a3d9a",
    label="SelenePlus, p=3 (un trabajo)",
)
ax.set_xticks([6, 8, 10, 12])
ax.set_xlabel("Número de nodos")
ax.set_ylabel("Probabilidad de óptimo en un tiro (%)")
ax.set_title("La solución óptima se vuelve menos probable al escalar")
ax.grid(alpha=0.25, which="both")
ax.legend()
fig.tight_layout()
fig.savefig(FIGURAS / "02_probabilidad_optimo_por_tiro.png", dpi=240)
plt.close(fig)


# 3. Comparación por rendimiento medio. Se omite el control aleatorio de la
# figura para no comprimir las diferencias; permanece en la tabla final.
fig, ax = plt.subplots(figsize=(11, 6))
for metodo in ["Greedy", "Recocido simulado", "Goemans-Williamson"]:
    datos = clasicos[clasicos["metodo"].eq(metodo)].sort_values("n")
    ax.plot(
        datos["n"],
        datos["razon_media"],
        marker="o",
        label=metodo,
    )

q3 = qaoa[qaoa["p"].eq(3)].sort_values("n")
ax.errorbar(
    q3["n"],
    q3["razon_muestral_media"],
    yerr=q3["razon_muestral_std"],
    marker="s",
    capsize=4,
    linewidth=2.3,
    color="#6a3d9a",
    label="QAOA ideal p=3: media de 30 lotes",
)
ax.plot(
    selene_ordenado["n"],
    selene_ordenado["razon_seleneplus"],
    marker="D",
    linewidth=2.0,
    color="#e31a1c",
    label="SelenePlus p=3: un trabajo",
)
ax.axhline(1.0, color="black", linestyle=":", linewidth=1.2, label="Óptimo")
ax.set_xticks([6, 8, 10, 12])
ax.set_ylim(0.82, 1.01)
ax.set_xlabel("Número de nodos")
ax.set_ylabel("Razón de aproximación media")
ax.set_title("Comparación por calidad esperada, no por el mejor tiro")
ax.grid(alpha=0.25)
ax.legend(ncol=2, fontsize=8)
fig.tight_layout()
fig.savefig(FIGURAS / "03_comparacion_metodos_calidad_media.png", dpi=240)
plt.close(fig)


# 4. Intercambio calidad-costo. Cada punto indica una profundidad distinta.
operaciones = guppy[
    ["n", "p", "operaciones_zz", "operaciones_rx", "operaciones_h"]
].drop_duplicates(["n", "p"])
tradeoff = qaoa.merge(operaciones, on=["n", "p"], how="left")

fig, ax = plt.subplots(figsize=(10, 6))
for n in sorted(tradeoff["n"].unique()):
    datos = tradeoff[tradeoff["n"].eq(n)].sort_values("p")
    ax.plot(
        datos["operaciones_zz"],
        datos["razon_ideal"],
        marker="o",
        linewidth=2,
        color=colores[n],
        label=f"G{n}",
    )
    for _, fila in datos.iterrows():
        ax.annotate(
            f"p={int(fila['p'])}",
            (fila["operaciones_zz"], fila["razon_ideal"]),
            xytext=(4, 6),
            textcoords="offset points",
            fontsize=8,
        )
ax.set_xlabel("Operaciones ZZ del circuito")
ax.set_ylabel("Razón de aproximación ideal")
ax.set_title("Más profundidad mejora la calidad, pero aumenta el costo")
ax.grid(alpha=0.25)
ax.legend()
fig.tight_layout()
fig.savefig(FIGURAS / "04_tradeoff_calidad_operaciones_zz.png", dpi=240)
plt.close(fig)


# 5. Robustez de la optimización: distribución de reinicios en p=3.
p3_reinicios = reinicios[reinicios["p"].eq(3)].copy()
grupos = [
    p3_reinicios[p3_reinicios["n"].eq(n)]["razon_esperada"].to_numpy()
    for n in (6, 8, 10, 12)
]
fig, ax = plt.subplots(figsize=(9, 5.8))
ax.boxplot(
    grupos,
    tick_labels=["G6", "G8", "G10", "G12"],
    showmeans=True,
)
rng = np.random.default_rng(2026)
for posicion, valores in enumerate(grupos, start=1):
    jitter = rng.normal(0, 0.035, size=len(valores))
    ax.scatter(
        posicion + jitter,
        valores,
        s=24,
        alpha=0.65,
        color="#4C78A8",
        zorder=3,
    )
    ax.scatter(
        posicion,
        valores.max(),
        marker="*",
        s=150,
        color="#E45756",
        zorder=4,
    )
ax.set_ylabel("Razón esperada")
ax.set_title("p=3: sensibilidad a la inicialización del optimizador")
ax.grid(axis="y", alpha=0.25)
fig.tight_layout()
fig.savefig(FIGURAS / "05_robustez_reinicios_p3.png", dpi=240)
plt.close(fig)

# 6. Comparación directa entre el valor ideal y el trabajo ruidoso.
# Las barras emparejadas muestran el desempeño absoluto y las etiquetas
# cuantifican la degradación observada. Solo existe un trabajo remoto por
# grafo, por lo que no se dibujan barras de error para SelenePlus.
x = np.arange(len(selene_ordenado))
ancho = 0.36
ideal_p3 = selene_ordenado["razon_ideal"].to_numpy()
ruidoso_p3 = selene_ordenado["razon_seleneplus"].to_numpy()
delta_p3 = ruidoso_p3 - ideal_p3

fig, ax = plt.subplots(figsize=(10, 6))
barras_ideal = ax.bar(
    x - ancho / 2,
    ideal_p3,
    ancho,
    color="#4C78A8",
    label="Simulación ideal local",
)
barras_ruido = ax.bar(
    x + ancho / 2,
    ruidoso_p3,
    ancho,
    color="#E45756",
    label="SelenePlus con ruido",
)
ax.bar_label(barras_ideal, fmt="%.3f", padding=3, fontsize=9)
ax.bar_label(barras_ruido, fmt="%.3f", padding=3, fontsize=9)
for posicion, ideal, delta in zip(x, ideal_p3, delta_p3):
    ax.annotate(
        f"Δ {delta:.3f}",
        (posicion, ideal + 0.045),
        ha="center",
        va="bottom",
        fontsize=9,
        fontweight="bold",
    )
ax.set_xticks(x, [f"G{int(n)}" for n in selene_ordenado["n"]])
ax.set_ylim(0, 1.08)
ax.set_xlabel("Instancia del grafo")
ax.set_ylabel("Razón de aproximación")
ax.set_title("Efecto observado del ruido en QAOA (p=3, 512 tiros)")
ax.grid(axis="y", alpha=0.25)
ax.legend()
fig.tight_layout()
fig.savefig(FIGURAS / "06_ideal_vs_seleneplus_p3.png", dpi=240)
plt.close(fig)


# Tabla 1: profundidad, calidad, probabilidad y costo.
tradeoff = tradeoff.sort_values(["n", "p"]).copy()
tradeoff["delta_razon_vs_p_anterior"] = tradeoff.groupby("n")[
    "razon_ideal"
].diff()
tradeoff["delta_zz_vs_p_anterior"] = tradeoff.groupby("n")[
    "operaciones_zz"
].diff()
tradeoff["ganancia_por_zz_adicional"] = (
    tradeoff["delta_razon_vs_p_anterior"]
    / tradeoff["delta_zz_vs_p_anterior"]
)
tradeoff["optimos_esperados_en_512"] = (
    512 * tradeoff["probabilidad_optimo_ideal"]
)
tabla_tradeoff = tradeoff[
    [
        "n",
        "p",
        "razon_ideal",
        "razon_muestral_media",
        "razon_muestral_std",
        "probabilidad_optimo_ideal",
        "optimos_esperados_en_512",
        "operaciones_h",
        "operaciones_rx",
        "operaciones_zz",
        "delta_razon_vs_p_anterior",
        "ganancia_por_zz_adicional",
    ]
]
tabla_tradeoff.to_csv(TABLAS / "01_tradeoff_profundidad.csv", index=False)


# Tabla 2: comparación justa por calidad media.
filas_metodos = []
for _, fila in clasicos.iterrows():
    filas_metodos.append(
        {
            "n": int(fila["n"]),
            "metodo": fila["metodo"],
            "razon_media": fila["razon_media"],
            "desviacion_razon": (
                fila["desviacion"] / fila["optimo_exacto"]
                if pd.notna(fila["desviacion"])
                else np.nan
            ),
            "repeticiones_o_evaluaciones": int(fila["ejecuciones"]),
            "origen": "clásico",
        }
    )
for _, fila in q3.iterrows():
    filas_metodos.append(
        {
            "n": int(fila["n"]),
            "metodo": "QAOA ideal p=3, 512 tiros",
            "razon_media": fila["razon_muestral_media"],
            "desviacion_razon": fila["razon_muestral_std"],
            "repeticiones_o_evaluaciones": 30,
            "origen": "30 lotes del mismo estado ideal optimizado",
        }
    )
for _, fila in selene_ordenado.iterrows():
    filas_metodos.append(
        {
            "n": int(fila["n"]),
            "metodo": "SelenePlus p=3, 512 tiros",
            "razon_media": fila["razon_seleneplus"],
            "desviacion_razon": np.nan,
            "repeticiones_o_evaluaciones": 1,
            "origen": "un trabajo remoto con ruido",
        }
    )
pd.DataFrame(filas_metodos).sort_values(["n", "metodo"]).to_csv(
    TABLAS / "02_comparacion_metodos_media.csv",
    index=False,
)


# Tabla 3: efecto observado en SelenePlus. Un solo trabajo no permite estimar
# variabilidad entre trabajos.
selene_tabla = selene_ordenado[
    [
        "n",
        "shots",
        "razon_ideal",
        "razon_seleneplus",
        "probabilidad_optimo_seleneplus",
        "job_id",
        "estado",
    ]
].copy()
selene_tabla["delta_razon_selene_menos_ideal"] = (
    selene_tabla["razon_seleneplus"] - selene_tabla["razon_ideal"]
)
selene_tabla["trabajos_remotos"] = 1
selene_tabla.to_csv(
    TABLAS / "03_seleneplus_vs_ideal_p3.csv",
    index=False,
)


# Tabla 4: estabilidad del optimizador y selección del mejor reinicio.
tabla_reinicios = (
    p3_reinicios.groupby("n")
    .agg(
        reinicios=("razon_esperada", "size"),
        convergencias=("convergencia_scipy", "sum"),
        media=("razon_esperada", "mean"),
        mediana=("razon_esperada", "median"),
        desviacion=("razon_esperada", "std"),
        peor=("razon_esperada", "min"),
        mejor_reinicio=("razon_esperada", "max"),
    )
    .reset_index()
)
tabla_reinicios.to_csv(
    TABLAS / "04_robustez_optimizacion_p3.csv",
    index=False,
)

print("Seis figuras y cuatro tablas finales regeneradas correctamente.")

# Quantathon CR 2026 · Challenge 1

Solución reproducible de Max-Cut ponderado sobre cuatro subgrafos reales de
la red de transmisión del ICE, usando QUBO, líneas base clásicas y QAOA con
Guppy.

## Estado verificable

- Región: Central.
- Instancias: G6, G8, G10 y G12.
- Profundidades QAOA: p=1, p=2 y p=3.
- Optimización: 6, 10 y 12 reinicios por profundidad, respectivamente.
- Variabilidad de optimización: 6, 10 y 12 inicializaciones para p=1, p=2 y
  p=3, respectivamente.
- Incertidumbre de muestreo complementaria: 30 lotes de 512 tiros del mismo
  estado optimizado para cada combinación de tamaño y profundidad.
- Guppy local: 12 configuraciones validadas con 512 tiros.
- SelenePlus: G6/G8/G10/G12, p=3, 512 tiros, con `HeliosRuntime` y
  `QSystemErrorModel(alpha)`.
- Resultado SelenePlus: cuatro grafos completados en un único trabajo remoto.
  No se presenta como ejecución en hardware físico.

## Punto único de entrada

La ruta recomendada regenera las seis figuras y las cuatro tablas desde los
resultados detallados incluidos, actualiza el manifiesto y valida la entrega:

```bash
python scripts/ejecutar_entrega.py
```

Para recalcular el flujo local desde los grafos y después regenerar todos los
productos finales:

```bash
python scripts/ejecutar_entrega.py --modo completo
```

Este modo reconstruye primero G6/G8/G10/G12 desde `datos/crudos/` mediante
`scripts/construir_grafo_ice.py`, publica automáticamente la salida canónica
en `datos/grafos/` y luego ejecuta y guarda los notebooks. `build/` es
únicamente un área temporal regenerable y no forma parte de la entrega.

La recuperación del trabajo SelenePlus existente es explícita y nunca habilita
un envío nuevo:

```bash
# 1. Clone the repository
git clone https://github.com/noir-technologies/quantathon2026-noir-powergrid.git
cd quantathon2026-noir-powergrid

# 2. Create and activate a virtual environment
python -m venv .venv
source .venv/bin/activate      # Windows: .venv\Scripts\activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Run the full pipeline
python run_all.py

# Optional flags
python run_all.py --p-max 3 --n-runs 10 --seed 42
```

All figures are saved to `results/figures/` and raw run data to `results/runs/`.

---

## Methods

### 1. Graph Construction
The ICE power transmission network is modeled as a weighted graph G = (V, E) with 6–12 nodes. Edge weights represent transmission line capacity. Source: [datos-ice-se.opendata.arcgis.com](https://datos-ice-se.opendata.arcgis.com).

### 2. QUBO Formulation
Max-Cut is cast as a QUBO: **minimize xᵀ Q x**, where x ∈ {0,1}ⁿ encodes node partitions. The QUBO is verified on small test instances (brute force) before running on the ICE graph.

### 3. QAOA Implementation
The QUBO maps to an Ising cost Hamiltonian H_C. QAOA builds a parameterized circuit with **p layers** of alternating `e^(-iγH_C)` and `e^(-iβH_B)` gates, classically optimized with BFGS.

**We run ≥ 5 independent initializations per p value and report mean ± std of the approximation ratio.**

### 4. Classical Baselines
| Method | Approximation Ratio |
|---|---|
| Greedy | ~0.5 |
| Goemans-Williamson (SDP) | ≥ 0.878 |
| Brute Force | Optimal (exact) |

Reference: Goemans & Williamson (1995), JACM 42(6).

---

## Key Results

> 🔄 *Results will be filled in after runs complete.*

| Method | Approximation Ratio r | Notes |
|---|---|---|
| Greedy | — | Baseline lower bound |
| Goemans-Williamson | — | Classical state-of-the-art |
| QAOA p=1 | — | mean ± std, ≥5 runs |
| QAOA p=2 | — | mean ± std, ≥5 runs |
| QAOA p=3 | — | mean ± std, ≥5 runs |

**Target:** QAOA at p=1 achieving r ≥ 0.6 on the 6-node test instance.

---

## Honest Limitations

As required by the judging rubric:

- QAOA does **not** currently outperform Goemans-Williamson for Max-Cut on any graph instance.
- At p=1, the guaranteed approximation ratio (0.6924) is strictly below GW (0.878).
- Results on the Quantinuum H2 **emulator** do not account for real hardware noise.
- Runtime scales exponentially with graph size for brute-force; GW is polynomial.

---

## Submission Checklist

- [ ] Graph data file with nodes, edges, weights, and ICE source
- [ ] QUBO formulation with documented penalty terms (`src/qaoa/qubo.py`)
- [ ] Approximation ratio plot: r vs. p (with error bars)
- [ ] GW + greedy baseline numbers
- [ ] Honest limitations section (above)
- [ ] Technical report PDF (max 8 pages)
- [ ] 5-minute presentation slides
- [ ] SDK statement ≤ 200 words (`docs/sdk_statement.md`)
- [ ] `run_all.py` reproduces all figures from a clean environment

---

## References

- Farhi, E., Goldstone, J., & Gutmann, S. (2014). A Quantum Approximate Optimization Algorithm. [arXiv:1411.4028](https://arxiv.org/abs/1411.4028)
- Goemans, M. X., & Williamson, D. P. (1995). Improved approximation algorithms for maximum cut and satisfiability problems using semidefinite programming. *JACM 42*(6), 1115–1145.
- Blekos, K. et al. (2024). A review on Quantum Approximate Optimization Algorithm and its variants.
- Jin, Y. et al. (2025). Iceberg QEC code. [arXiv:2504.21172](https://arxiv.org/abs/2504.21172)
- ICE Open Data: [datos-ice-se.opendata.arcgis.com](https://datos-ice-se.opendata.arcgis.com)

---

## Team

**NOIR Technologies** · Quantum Computing Lab · Universidad Cenfotec, Costa Rica

| Name | Role |
|---|---|
| *(Add team members)* | *(Add roles)* |

---

*Quantathon CR 2026 — Judges reward rigour and honesty over ambition. A modest, well-scoped, fully reproducible result scores higher than an impressive-sounding claim that cannot be verified.*
python scripts/ejecutar_entrega.py --modo completo --recuperar-seleneplus
```

También existe una comprobación rápida que no modifica resultados:

```bash
python scripts/ejecutar_entrega.py --modo validar
```

Para instalar:

```bash
python -m pip install -r requirements.txt
```

Los notebooks permanecen separados para facilitar la revisión técnica, pero el
script anterior es el punto de entrada reproducible.

## Estructura

- `datos/crudos/`: capas, catálogos y fuentes oficiales.
- `datos/grafos/`: G6/G8/G10/G12 en CSV y GraphML.
- `scripts/construir_grafo_ice.py`: constructor definitivo de los grafos.
- `resultados/clasicos/`: QUBO, exacto, greedy, recocido y GW.
- `resultados/qaoa_local/`: optimizaciones, mediciones y resúmenes.
- `resultados/remoto/`: evidencia SelenePlus separada.
- `resultados/tablas_finales/`: comparaciones de calidad, costo, ruido y
  robustez.
- `figuras/`: seis figuras finales, incluida la comparación directa entre
  simulación ideal y SelenePlus con ruido.
- `docs/`: auditoría, interpretación y guía de tiros.
- `build/`: salida temporal regenerable; se excluye del paquete final.

## Limitación central

Las cuatro instancias son árboles bipartitos con pesos positivos. Su Max-Cut
óptimo corta todas las aristas y coincide con la suma de pesos. Esto permite
validar con rigor el flujo QUBO/QAOA, pero no representa una instancia
clásicamente difícil y no respalda una afirmación de ventaja cuántica.

Por esta razón, la entrega no utiliza «la mejor solución observada» como
métrica principal: con 512 tiros esa medida se satura en 1.0. Se reportan la
calidad esperada, la probabilidad de óptimo por tiro, la variabilidad entre
reinicios y el intercambio entre profundidad y operaciones ZZ.

No se añadieron aristas artificiales: se priorizó la fidelidad a los datos del
ICE y la reproducibilidad.

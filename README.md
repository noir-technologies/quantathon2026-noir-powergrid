# ⚡ Quantathon CR 2026 · Challenge 1
## Sustainable, Resilient & Green Power Grid — Fault-Zone Partitioning via QAOA

**Team:** NOIR Technologies · Universidad Cenfotec — Quantum Computing Lab  
**Event:** Quantathon CR 2026  
**Challenge:** 1 — Red Eléctrica Sostenible, Resiliente y Verde (Max-Cut / QAOA)  
**Emulator:** Quantinuum H2  
**SDGs:** 🌱 SDG 7 · SDG 9 · SDG 13

---

## Problem Overview

Fault-zone partitioning divides a power grid into segments that can isolate themselves during a fault, preventing local outages from cascading into massive blackouts. This maps directly to a **Max-Cut problem (NP-hard)**, which we solve using **QAOA (Quantum Approximate Optimization Algorithm)** after casting it as a **QUBO (Quadratic Unconstrained Binary Optimization)**.

Our graph instance is derived from real Costa Rican transmission data provided by the **Instituto Costarricense de Electricidad (ICE)** — [datos-ice-se.opendata.arcgis.com](https://datos-ice-se.opendata.arcgis.com).

---

## Repository Structure

```
quantathon2026-noir-powergrid/
├── run_all.py                  # 🚀 Single entry point — reproduces all figures & results
├── config.yaml                 # Centralized parameters for reproducibility
├── requirements.txt
│
├── data/
│   ├── raw/                    # ICE grid data (nodes, edges, weights, source)
│   └── processed/              # Cleaned graph files
│
├── src/
│   ├── qaoa/
│   │   ├── circuit.py          # QAOA circuit construction & execution
│   │   └── qubo.py             # Max-Cut → QUBO formulation
│   ├── classical/
│   │   └── baselines.py        # Greedy, Goemans-Williamson, Brute Force
│   └── utils/
│       ├── graph_loader.py     # ICE data loading & preprocessing
│       └── reporting.py        # Figure generation
│
├── notebooks/
│   └── 01_exploration.ipynb    # Exploratory analysis
│
├── results/
│   ├── figures/                # All generated plots (committed)
│   └── runs/                   # Raw JSON results per run
│
├── tests/
│   ├── test_qubo.py
│   └── test_baselines.py
│
└── docs/
    └── sdk_statement.md        # ≤200-word SDK reflection (submission requirement)
```

---

## Quickstart — Reproduce All Results

> **Requirement:** Every figure and number in the technical report must be reproducible from a clean environment using the commands below.

```bash
# 1. Clone the repository
git clone https://github.com/NOIR-Technologies-Cenfotec/quantathon2026-noir-powergrid.git
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

"""
NOIR Technologies – Quantathon CR 2026 · Challenge 1
Entry point: reproduce every figure and number reported in the technical report.

Usage:
    python run_all.py

Outputs are written to results/figures/ and results/runs/.
"""

import argparse
from src.utils.config import load_config

def main():
    parser = argparse.ArgumentParser(description="Run full QAOA pipeline for Challenge 1")
    parser.add_argument("--config", default="config.yaml", help="Path to config file")
    parser.add_argument("--p-max", type=int, default=3, help="Maximum QAOA depth p")
    parser.add_argument("--n-runs", type=int, default=10, help="Number of independent runs (min 5)")
    parser.add_argument("--seed", type=int, default=42, help="Random seed for reproducibility")
    args = parser.parse_args()

    print("=" * 60)
    print("NOIR Technologies · Quantathon CR 2026 · Challenge 1")
    print("Sustainable, Resilient & Green Power Grid (Max-Cut / QAOA)")
    print("=" * 60)

    print("\n[1/4] Loading ICE power grid graph...")
    # from src.utils.graph_loader import load_ice_graph
    # G = load_ice_graph()

    print("[2/4] Computing classical baselines (Greedy + Goemans-Williamson)...")
    # from src.classical.baselines import run_baselines
    # baselines = run_baselines(G)

    print("[3/4] Running QAOA for p = 1 to", args.p_max, "...")
    # from src.qaoa.pipeline import run_qaoa_sweep
    # qaoa_results = run_qaoa_sweep(G, p_max=args.p_max, n_runs=args.n_runs, seed=args.seed)

    print("[4/4] Generating figures and summary table...")
    # from src.utils.reporting import generate_all_figures
    # generate_all_figures(baselines, qaoa_results)

    print("\nDone. Check results/figures/ for plots and results/runs/ for raw data.")

if __name__ == "__main__":
    main()

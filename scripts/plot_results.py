#!/usr/bin/env python3
"""
plot_results.py — generate figures from parsed CS152 results.

Consumes results/<lab>.json (written by parse_results.py) and regenerates the
plots that used to be hand-coded in labs/lab1/submission.py, plus a couple of
useful additions (lab2 cache comparison, lab4 vector speedup). Data is read from
the JSON, never hard-coded — re-run the labs, re-parse, re-plot.

Usage:
    scripts/plot_results.py                 # all labs with results
    scripts/plot_results.py lab1 lab4
    scripts/plot_results.py --outdir latex/figures   # write where LaTeX expects

Figures are written to results/figures/<lab>/ by default.
"""
import argparse
import json
import os
import sys

import matplotlib
matplotlib.use("Agg")           # headless
import matplotlib.pyplot as plt
import numpy as np

FIGSIZE = (10, 5)
DPI = 200


def load(root, lab):
    path = os.path.join(root, "results", f"{lab}.json")
    if not os.path.isfile(path):
        return None
    with open(path) as f:
        return json.load(f)


def _benches(cfg_data):
    """Stable benchmark ordering shared across configs."""
    return sorted(cfg_data)


def save(fig_dir, name):
    os.makedirs(fig_dir, exist_ok=True)
    path = os.path.join(fig_dir, name)
    plt.savefig(path, bbox_inches="tight")
    plt.clf()
    plt.close()
    return path


# --------------------------------------------------------------------------
# lab1 — Sodor pipelines
# --------------------------------------------------------------------------

def plot_lab1(data, fig_dir):
    made = []

    # 1) Instruction breakdown (per config that has the breakdown fields)
    for cfg, benches in sorted(data.items()):
        rows = {b: m for b, m in benches.items() if "arithmetic" in m}
        if not rows:
            continue
        names = sorted(rows)
        x = np.arange(len(names))
        arith = [rows[b]["arithmetic"] for b in names]
        ldst = [rows[b]["ldst"] for b in names]
        branch = [rows[b]["branch"] for b in names]
        plt.figure(figsize=FIGSIZE, dpi=DPI)
        plt.bar(x - 0.2, arith, 0.2, label="Arithmetic")
        plt.bar(x, ldst, 0.2, label="Memory (Ld/St)")
        plt.bar(x + 0.2, branch, 0.2, label="Control (Branch/Jump)")
        plt.title(f"Instruction Breakdown — {cfg}")
        plt.xticks(x, names, rotation=20)
        plt.xlabel("Benchmark"); plt.ylabel("Intensity (%)"); plt.legend()
        made.append(save(fig_dir, f"lab1_breakdown_{cfg}.png"))

    # 2) CPI comparison across all configs that report CPI
    cfgs = [c for c in sorted(data) if any("cpi" in m for m in data[c].values())]
    if cfgs:
        names = sorted({b for c in cfgs for b in data[c]})
        x = np.arange(len(names))
        width = 0.8 / max(len(cfgs), 1)
        plt.figure(figsize=FIGSIZE, dpi=DPI)
        for i, c in enumerate(cfgs):
            cpis = [data[c].get(b, {}).get("cpi", 0) for b in names]
            plt.bar(x + (i - (len(cfgs) - 1) / 2) * width, cpis, width, label=c)
        plt.title("CPI by Benchmark across Pipeline Configurations")
        plt.xticks(x, names, rotation=20)
        plt.xlabel("Benchmark"); plt.ylabel("CPI"); plt.legend()
        made.append(save(fig_dir, "lab1_cpi_comparison.png"))

    return made


# --------------------------------------------------------------------------
# lab2 — Rocket caches
# --------------------------------------------------------------------------

def plot_lab2(data, fig_dir):
    made = []
    benchset = sorted({b for c in data.values() for b in c})
    cfgs = sorted(data)
    for metric, title, fname in (
        ("cycles", "Cycles", "lab2_cycles.png"),
        ("d$ regular miss", "L1 D$ Regular Misses", "lab2_dcache_miss.png"),
    ):
        if not any(metric in data[c].get(b, {}) for c in cfgs for b in benchset):
            continue
        x = np.arange(len(benchset))
        width = 0.8 / max(len(cfgs), 1)
        plt.figure(figsize=FIGSIZE, dpi=DPI)
        for i, c in enumerate(cfgs):
            vals = [data[c].get(b, {}).get(metric, 0) for b in benchset]
            plt.bar(x + (i - (len(cfgs) - 1) / 2) * width, vals, width, label=c)
        plt.title(f"{title} by Configuration")
        plt.xticks(x, benchset, rotation=20)
        plt.xlabel("Benchmark"); plt.ylabel(title); plt.legend()
        made.append(save(fig_dir, fname))
    return made


# --------------------------------------------------------------------------
# lab4 — RVV scalar vs vector
# --------------------------------------------------------------------------

def plot_lab4(data, fig_dir):
    made = []
    scalar = data.get("scalar", {})
    vector = data.get("vector", {})
    # Pair scalar X with vector vec-X
    pairs = [(b, f"vec-{b}") for b in sorted(scalar)
             if f"vec-{b}" in vector]
    if not pairs:
        return made
    names = [p[0] for p in pairs]
    x = np.arange(len(names))
    scyc = [scalar[s]["mcycle"] for s, _ in pairs]
    vcyc = [vector[v]["mcycle"] for _, v in pairs]

    plt.figure(figsize=FIGSIZE, dpi=DPI)
    plt.bar(x - 0.2, scyc, 0.4, label="Scalar")
    plt.bar(x + 0.2, vcyc, 0.4, label="Vector")
    plt.title("Scalar vs Vector Cycles (Spike)")
    plt.xticks(x, names, rotation=20)
    plt.xlabel("Benchmark"); plt.ylabel("mcycle"); plt.yscale("log"); plt.legend()
    made.append(save(fig_dir, "lab4_scalar_vs_vector.png"))

    plt.figure(figsize=FIGSIZE, dpi=DPI)
    speedup = [s / v if v else 0 for s, v in zip(scyc, vcyc)]
    plt.bar(names, speedup, color="seagreen")
    for i, sp in enumerate(speedup):
        plt.text(i, sp, f"{sp:.1f}x", ha="center", va="bottom")
    plt.title("Vectorization Speedup")
    plt.xticks(rotation=20)
    plt.xlabel("Benchmark"); plt.ylabel("Speedup (scalar / vector cycles)")
    made.append(save(fig_dir, "lab4_speedup.png"))
    return made


PLOTTERS = {"lab1": plot_lab1, "lab2": plot_lab2, "lab4": plot_lab4}


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("labs", nargs="*", help="labs to plot (default: all available)")
    ap.add_argument("--root", default=os.path.dirname(os.path.dirname(
                    os.path.abspath(__file__))))
    ap.add_argument("--outdir", default=None,
                    help="figure output dir (default: results/figures/<lab>)")
    args = ap.parse_args()

    labs = args.labs or list(PLOTTERS)
    made_any = False
    for lab in labs:
        if lab not in PLOTTERS:
            print(f"[skip] no plotter for {lab}", file=sys.stderr)
            continue
        data = load(args.root, lab)
        if not data:
            print(f"[warn] no results/{lab}.json (run parse_results.py first)",
                  file=sys.stderr)
            continue
        fig_dir = args.outdir or os.path.join(args.root, "results", "figures", lab)
        made = PLOTTERS[lab](data, fig_dir)
        for p in made:
            print(f"[ok] {os.path.relpath(p, args.root)}")
        made_any = made_any or bool(made)

    return 0 if made_any else 1


if __name__ == "__main__":
    sys.exit(main())

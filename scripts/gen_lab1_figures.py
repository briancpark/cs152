#!/usr/bin/env python3
"""
gen_lab1_figures.py — regenerate the exact figures + tables that lab1.tex uses,
straight from parsed simulator data (results/lab1.json). This replaces the
hard-coded lists in labs/lab1/submission.py: nothing is transcribed by hand.

Produces (into --outdir, default latex/figures/):
    3_4.png     instruction breakdown (Sodor1Stage)
    3_5_1.png   derived "New CPI"                 + table -> results/tables/lab1_3_5_1.tex
    3_5_2.png   derived CPI, loads/stores at CPI 1 + table -> results/tables/lab1_3_5_2.tex
    3_5_3.png   comparison of the two CPIs
    3_6.png     5-stage CPI: bypassing vs interlocking + table (if both present)

Derived-CPI model (identical to the original submission.py):
    CPI = (arith + W_mem*ldst + 1.5*branch + 1.5*misc)/100 * cycles/instructions
    3.5.1 uses W_mem=2 (memory 2x); 3.5.2 uses W_mem=1 (loads/stores at CPI 1).

Usage:
    scripts/gen_lab1_figures.py [--outdir DIR] [--bypass-config NAME]
                                [--interlock-config NAME]
"""
import argparse
import json
import os
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

ORDER = ["dhrystone", "median", "multiply", "qsort", "rsort", "towers", "vvadd"]
FIGSIZE = (10, 5)
DPI = 440


def load(root):
    path = os.path.join(root, "results", "lab1.json")
    if not os.path.isfile(path):
        sys.exit(f"error: {path} not found — run parse_results.py lab1 first")
    with open(path) as f:
        return json.load(f)


def benches_in(cfg, present):
    """Benchmarks from ORDER that exist in cfg (keeps report ordering)."""
    return [b for b in ORDER if b in present.get(cfg, {})]


def derived_cpi(m, w_mem):
    return (m["arithmetic"] + w_mem * m["ldst"] + 1.5 * m["branch"]
            + 1.5 * m["misc"]) / 100 * m["cycles"] / m["instructions"]


def latex_table(caption, header, rows):
    cols = "c " * len(header)
    out = [r"\begin{table}[ht]", rf"\caption{{{caption}}}", r"\centering",
           rf"\begin{{tabular}}{{{cols.strip()}}}", r"\hline\hline",
           " & ".join(header) + r" \\ [0.5ex]", r"\hline"]
    for r in rows:
        out.append(" & ".join(r) + r" \\")
    out += [r"[1ex]", r"\hline", r"\end{tabular}", r"\end{table}", ""]
    return "\n".join(out)


def save(outdir, name):
    os.makedirs(outdir, exist_ok=True)
    plt.savefig(os.path.join(outdir, name), bbox_inches="tight")
    plt.clf(); plt.close()
    return os.path.join(outdir, name)


def main():
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", default=root)
    ap.add_argument("--outdir", default=os.path.join(root, "latex", "figures"),
                    help="where to write figures (default: latex/figures)")
    ap.add_argument("--tabdir", default=None,
                    help="where to write LaTeX tables (default: <outdir>/../tables)")
    ap.add_argument("--bypass-config", default="Sodor5StageConfig",
                    help="config used as 5-stage 'full bypassing' (default Sodor5StageConfig)")
    ap.add_argument("--interlock-config", default="Sodor5StageNoBypassConfig",
                    help="config used as 5-stage 'full interlocking' (if built)")
    args = ap.parse_args()

    data = load(args.root)
    tabdir = args.tabdir or os.path.join(os.path.dirname(args.outdir), "tables")
    os.makedirs(tabdir, exist_ok=True)
    made = []

    # ---- 3.4 instruction breakdown (Sodor1Stage) -----------------------
    s1 = "Sodor1StageConfig"
    bs = benches_in(s1, data)
    if not bs:
        sys.exit("error: no Sodor1StageConfig breakdown data; run the 1-stage suite")
    x = np.arange(len(bs))
    arith = [data[s1][b]["arithmetic"] for b in bs]
    mem = [data[s1][b]["ldst"] for b in bs]
    ctrl = [data[s1][b]["branch"] for b in bs]
    plt.figure(figsize=FIGSIZE, dpi=DPI)
    plt.bar(x - 0.2, arith, 0.2, label="Arithmetic")
    plt.bar(x, mem, 0.2, label="Memory")
    plt.bar(x + 0.2, ctrl, 0.2, label="Control")
    plt.title("Benchmark by Instruction Breakdown")
    plt.xticks(x, bs); plt.xlabel("Benchmarks"); plt.ylabel("Intensity (%)"); plt.legend()
    made.append(save(args.outdir, "3_4.png"))

    # ---- 3.5 derived CPIs + tables -------------------------------------
    cpi1 = [derived_cpi(data[s1][b], 2) for b in bs]   # memory 2x
    cpi2 = [derived_cpi(data[s1][b], 1) for b in bs]   # loads/stores at CPI 1

    plt.figure(figsize=FIGSIZE, dpi=DPI)
    plt.bar(bs, cpi1); plt.title("New CPI for Benchmarks")
    plt.xlabel("Benchmarks"); plt.ylabel("CPI")
    made.append(save(args.outdir, "3_5_1.png"))

    plt.figure(figsize=FIGSIZE, dpi=DPI)
    plt.bar(bs, cpi2); plt.title("New CPI for Benchmarks (Loads/Stores at CPI 1)")
    plt.xlabel("Benchmarks"); plt.ylabel("CPI")
    made.append(save(args.outdir, "3_5_2.png"))

    # 3.5.3 comparison (second series scaled by 30% cycle-time, as in submission.py)
    cpi2_ct = [c * 1.3 for c in cpi2]
    plt.figure(figsize=FIGSIZE, dpi=DPI)
    plt.bar(x - 0.2, cpi1, 0.4, label="Modified CPI")
    plt.bar(x + 0.2, cpi2_ct, 0.4,
            label="Modified CPI, Memory Optimized + 30% Cycle Time")
    plt.title("CPI Comparison"); plt.xticks(x, bs)
    plt.xlabel("Benchmarks"); plt.ylabel("CPI"); plt.legend(loc="lower right")
    made.append(save(args.outdir, "3_5_3.png"))

    with open(os.path.join(tabdir, "lab1_3_5_1.tex"), "w") as f:
        f.write(latex_table("New CPI for Benchmarks", ["Benchmark", "CPI\\#1"],
                            [[b, f"{c:.3f}"] for b, c in zip(bs, cpi1)]))
    with open(os.path.join(tabdir, "lab1_3_5_2.tex"), "w") as f:
        f.write(latex_table("New CPI for Benchmarks (Loads/Stores at CPI 1)",
                            ["Benchmark", "CPI\\#1"],
                            [[b, f"{c:.3f}"] for b, c in zip(bs, cpi2)]))

    # ---- 3.6 bypassing vs interlocking (5-stage) -----------------------
    # Only (re)generate when the no-bypass 5-stage was also built — otherwise a
    # bypass-only chart would be worse than the committed 3_6.png, so leave it.
    onc, offc = args.bypass_config, args.interlock_config
    on_bs = benches_in(onc, data)
    if on_bs and all(b in data.get(offc, {}) for b in on_bs):
        on = [data[onc][b]["cpi"] for b in on_bs]
        off = [data[offc][b]["cpi"] for b in on_bs]
        xx = np.arange(len(on_bs))
        plt.figure(figsize=FIGSIZE, dpi=DPI)
        plt.bar(xx - 0.2, on, 0.4, label="Full Bypassing")
        plt.bar(xx + 0.2, off, 0.4, label="Full Interlocking")
        plt.title("CPI: 5-Stage Full Bypassing vs Full Interlocking")
        plt.xticks(xx, on_bs); plt.xlabel("Benchmarks"); plt.ylabel("CPI"); plt.legend()
        made.append(save(args.outdir, "3_6.png"))
        rows = [[b, f"{o:.3f}", f"{f:.3f}", f"{f/o:.3f}"]
                for b, o, f in zip(on_bs, on, off)]
        with open(os.path.join(tabdir, "lab1_3_6.tex"), "w") as fo:
            fo.write(latex_table("5-Stage CPI: Bypassing vs Interlocking",
                                 ["Benchmark", "CPI w/ Bypassing",
                                  "CPI w/ Interlocking", "Ratio"], rows))
    else:
        print("[note] 3_6: no interlocking (bypass-off) data — leaving the "
              "committed 3_6.png/table untouched. Build a no-bypass 5-stage "
              "config and re-parse to auto-generate it.", file=sys.stderr)

    for p in made:
        print(f"[ok] {os.path.relpath(p, args.root)}")
    print(f"[ok] tables -> {os.path.relpath(tabdir, args.root)}/lab1_3_5_1.tex, "
          "lab1_3_5_2.tex" + (", lab1_3_6.tex" if os.path.exists(
              os.path.join(tabdir, 'lab1_3_6.tex')) else ""))


if __name__ == "__main__":
    main()

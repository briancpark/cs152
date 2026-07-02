#!/usr/bin/env python3
"""
parse_results.py — harvest CS152 simulator output into structured data.

Replaces the manual step of copying numbers out of tracer.py / the simulator
logs into Python lists and LaTeX tables. It walks each lab's output directory,
parses the results, and writes JSON + CSV + LaTeX tables under results/.

Usage:
    scripts/parse_results.py lab1 [lab2] [lab4] ...   # default: all available
    scripts/parse_results.py --root /path/to/cs152

Data model (results/<lab>.json):
    { "<config>": { "<benchmark>": { metric: value, ... }, ... }, ... }

lab1 metrics : cpi, ipc, cycles, instructions, bubbles,
               arithmetic, ldst, branch, misc           (via tracer.py)
lab2 metrics : cycles, instret, loads, stores, i$ miss, d$ regular miss, ...
lab4 metrics : mcycle, minstret                          (scalar + vector)
"""
import argparse
import csv
import json
import os
import re
import subprocess
import sys

# --------------------------------------------------------------------------
# Parsers — each takes raw text, returns a flat {metric: number} dict
# --------------------------------------------------------------------------

def parse_tracer_stats(text):
    """Parse the output of riscv-sodor's tracer.py."""
    patterns = {
        "cpi":          r"CPI\s*:\s*([\d.]+)",
        "ipc":          r"IPC\s*:\s*([\d.]+)",
        "cycles":       r"Cycles\s*:\s*(\d+)",
        "instructions": r"Instructions\s*:\s*(\d+)",
        "bubbles":      r"Bubbles\s*:\s*(\d+)",
        "arithmetic":   r"%\s*Arithmetic\s*:\s*([\d.]+)",
        "ldst":         r"%\s*Ld/St\s*:\s*([\d.]+)",
        "branch":       r"%\s*Branch/Jump\s*:\s*([\d.]+)",
        "misc":         r"%\s*Misc\.?\s*:\s*([\d.]+)",
    }
    out = {}
    for key, pat in patterns.items():
        m = re.search(pat, text)
        if m:
            out[key] = float(m.group(1)) if "." in m.group(1) else int(m.group(1))
    return out


# "label : 12345" HPM-counter lines (lab2 / lab5 directed tests)
_HPM_LINE = re.compile(r"^\s*([A-Za-z][\w$./ -]*?)\s*:\s*(\d+)\s*$", re.MULTILINE)

def parse_hpm_stats(text):
    """Parse the `label : value` HPM-counter table printed by the directed tests."""
    out = {}
    for label, value in _HPM_LINE.findall(text):
        key = label.strip().lower()
        # skip tracer-style keys that also match (handled elsewhere)
        if key in ("cpi", "ipc"):
            continue
        out[key] = int(value)
    return out


def parse_mcycle(text):
    """Parse `mcycle = N` / `minstret = N` lines (Sodor & Spike printouts)."""
    out = {}
    for key, label in (("mcycle", "mcycle"), ("minstret", "minstret")):
        vals = re.findall(rf"{label}\s*=\s*(\d+)", text)
        if vals:
            out[key] = int(vals[-1])   # last printed value is the final count
    return out


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------

def read(path):
    try:
        with open(path, errors="replace") as f:
            return f.read()
    except OSError:
        return ""


def run_tracer(root, lab, out_file):
    """Run riscv-sodor's tracer.py on a Sodor .out and return its text."""
    tracer = os.path.join(root, "labs", lab,
                          "generators/riscv-sodor/scripts/tracer.py")
    if not os.path.isfile(tracer) or not os.path.isfile(out_file):
        return ""
    try:
        return subprocess.run([sys.executable, tracer, out_file],
                              capture_output=True, text=True, timeout=120).stdout
    except (subprocess.SubprocessError, OSError):
        return ""


def config_name(dirname):
    """chipyard.TestHarness.Sodor1StageConfig -> Sodor1StageConfig"""
    return dirname.split(".")[-1]


# --------------------------------------------------------------------------
# Per-lab collectors
# --------------------------------------------------------------------------

def collect_lab1(root):
    """Sodor pipelines: run tracer.py on every <config>/<bench>.out."""
    base = os.path.join(root, "labs/lab1/sims/verilator/output")
    data = {}
    if not os.path.isdir(base):
        return data
    for d in sorted(os.listdir(base)):
        cfgdir = os.path.join(base, d)
        if not os.path.isdir(cfgdir) or "Sodor" not in d:
            continue
        cfg = config_name(d)
        for f in sorted(os.listdir(cfgdir)):
            if not f.endswith(".out"):
                continue
            bench = f[:-4]
            out_path = os.path.join(cfgdir, f)
            stats = parse_mcycle(read(out_path))
            stats.update(parse_tracer_stats(run_tracer(root, "lab1", out_path)))
            if stats:
                data.setdefault(cfg, {})[bench] = stats
    return data


def collect_hpm_lab(root, lab):
    """lab2-style: parse the HPM table from each <config>/<bench>.log."""
    base = os.path.join(root, "labs", lab, "sims/verilator/output")
    data = {}
    if not os.path.isdir(base):
        return data
    for d in sorted(os.listdir(base)):
        cfgdir = os.path.join(base, d)
        if not os.path.isdir(cfgdir):
            continue
        cfg = config_name(d)
        for f in sorted(os.listdir(cfgdir)):
            if not f.endswith(".log"):
                continue
            bench = f[:-4]
            stats = parse_hpm_stats(read(os.path.join(cfgdir, f)))
            if stats:
                data.setdefault(cfg, {})[bench] = stats
    return data


def collect_lab4(root):
    """RVV: parse mcycle/minstret from benchmarks/<bench>.riscv.out."""
    base = os.path.join(root, "labs/lab4/benchmarks")
    data = {"scalar": {}, "vector": {}}
    if not os.path.isdir(base):
        return {}
    for f in sorted(os.listdir(base)):
        if not f.endswith(".result"):
            continue
        bench = f[:-len(".result")]
        stats = parse_mcycle(read(os.path.join(base, f)))
        if stats:
            group = "vector" if bench.startswith("vec-") else "scalar"
            data[group][bench] = stats
    return {k: v for k, v in data.items() if v}


COLLECTORS = {
    "lab1": collect_lab1,
    "lab2": lambda root: collect_hpm_lab(root, "lab2"),
    "lab4": collect_lab4,
}

# Preferred column order for CSV/LaTeX (others appended as discovered)
METRIC_ORDER = ["cpi", "ipc", "cycles", "instructions", "bubbles",
                "arithmetic", "ldst", "branch", "misc",
                "mcycle", "minstret", "instret", "loads", "stores"]


# --------------------------------------------------------------------------
# Writers
# --------------------------------------------------------------------------

def ordered_metrics(data):
    seen = []
    for cfg in data.values():
        for bench in cfg.values():
            for k in bench:
                if k not in seen:
                    seen.append(k)
    return sorted(seen, key=lambda k: (METRIC_ORDER.index(k)
                                       if k in METRIC_ORDER else 1e9, k))


def write_csv(data, path):
    metrics = ordered_metrics(data)
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["config", "benchmark"] + metrics)
        for cfg in sorted(data):
            for bench in sorted(data[cfg]):
                row = data[cfg][bench]
                w.writerow([cfg, bench] + [row.get(m, "") for m in metrics])


def tex_escape(s):
    """Escape LaTeX special chars in a header/label (e.g. d$ regular miss)."""
    for a, b in (("\\", r"\textbackslash{}"), ("&", r"\&"), ("%", r"\%"),
                 ("$", r"\$"), ("#", r"\#"), ("_", r"\_"), ("{", r"\{"),
                 ("}", r"\}")):
        s = s.replace(a, b)
    return s


def write_latex(data, path, lab):
    metrics = ordered_metrics(data)
    lines = [f"% Auto-generated by parse_results.py for {lab} — do not edit by hand"]
    for cfg in sorted(data):
        cols = "l" + "r" * len(metrics)
        lines += [r"\begin{table}[h]", r"\centering",
                  rf"\caption{{{tex_escape(lab)}: {tex_escape(cfg)}}}",
                  rf"\begin{{tabular}}{{{cols}}}", r"\toprule",
                  "benchmark & " + " & ".join(tex_escape(m) for m in metrics) + r" \\",
                  r"\midrule"]
        for bench in sorted(data[cfg]):
            row = data[cfg][bench]
            cells = []
            for m in metrics:
                v = row.get(m, "")
                cells.append(f"{v:g}" if isinstance(v, float) else str(v))
            lines.append(tex_escape(bench) + " & " + " & ".join(cells) + r" \\")
        lines += [r"\bottomrule", r"\end{tabular}", r"\end{table}", ""]
    with open(path, "w") as f:
        f.write("\n".join(lines))


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("labs", nargs="*", default=[], help="labs to parse (default: all)")
    ap.add_argument("--root", default=os.path.dirname(os.path.dirname(
                    os.path.abspath(__file__))), help="repo root")
    args = ap.parse_args()

    labs = args.labs or list(COLLECTORS)
    outdir = os.path.join(args.root, "results")
    os.makedirs(os.path.join(outdir, "tables"), exist_ok=True)

    any_data = False
    for lab in labs:
        if lab not in COLLECTORS:
            print(f"[skip] no collector for {lab}", file=sys.stderr)
            continue
        data = COLLECTORS[lab](args.root)
        if not data:
            print(f"[warn] no results found for {lab} "
                  f"(run ./run_labs.sh {lab} first)", file=sys.stderr)
            continue
        any_data = True
        json_path = os.path.join(outdir, f"{lab}.json")
        csv_path = os.path.join(outdir, f"{lab}.csv")
        tex_path = os.path.join(outdir, "tables", f"{lab}.tex")
        with open(json_path, "w") as f:
            json.dump(data, f, indent=2, sort_keys=True)
        write_csv(data, csv_path)
        write_latex(data, tex_path, lab)
        n = sum(len(v) for v in data.values())
        print(f"[ok] {lab}: {n} runs across {len(data)} configs "
              f"-> {os.path.relpath(json_path, args.root)}, .csv, tables/{lab}.tex")

    return 0 if any_data else 1


if __name__ == "__main__":
    sys.exit(main())

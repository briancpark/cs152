"""Lab 5 — cache coherence (dual-core Rocket).

Data: <test>.log per coherence config, containing the benchmark's
`<func>: N cycles, X cycles/iter, Y CPI` line.
"""
import re

from .common import grouped_bars, latex_table, new_fig, read, save, sim_outputs, write_table

PROTOCOLS = [("Lab5MIDualRocketConfig", "MI"), ("Lab5MSIDualRocketConfig", "MSI"),
             ("Lab5MESIDualRocketConfig", "MESI")]
TESTS = ["mt-vvadd-naive", "mt-vvadd-opt", "mt-matmul-naive", "mt-matmul-opt"]
_LINE = re.compile(r"(\w+): (\d+) cycles, ([\d.]+) cycles/iter, ([\d.]+) CPI")


def collect():
    data = {}
    for cfg, d in sim_outputs("lab5").items():
        for log in sorted(d.glob("*.log")):
            if log.name.endswith(".make.log"):
                continue
            m = _LINE.search(read(log))
            if m:
                data.setdefault(cfg, {})[log.stem] = {
                    "func": m.group(1), "cycles": int(m.group(2)),
                    "cycles_per_iter": float(m.group(3)), "cpi": float(m.group(4))}
    return data


def report(data):
    made = []
    protos = [(c, p) for c, p in PROTOCOLS if c in data]
    if not protos:
        return made
    rows = []
    for t in TESTS:
        for c, p in protos:
            r = data[c].get(t)
            if r:
                rows.append([t, p, r["cycles"], f"{r['cycles_per_iter']:.1f}", f"{r['cpi']:.1f}"])
    made.append(write_table("lab5", "summary", latex_table(
        "Multithreaded kernels on dual-core Rocket", ["Test", "Protocol", "Cycles", "Cycles/iter", "CPI"], rows)))

    for kernel in ("vvadd", "matmul"):
        tests = [t for t in TESTS if kernel in t]
        fig, ax = new_fig(figsize=(8, 4.5))
        grouped_bars(ax, [t.replace(f"mt-{kernel}-", "") for t in tests],
                     {p: [data[c].get(t, {}).get("cycles") for t in tests] for c, p in protos},
                     value_fmt="{:,.0f}")
        ax.set_title(f"mt-{kernel}: cycles by coherence protocol"); ax.set_ylabel("Cycles")
        made.append(save(fig, "lab5", kernel))
    return made

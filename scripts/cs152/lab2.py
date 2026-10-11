"""Lab 2 — Rocket caches.

Data: transpose-<variant>.log HPM dumps per config, and caches_<size>_<iters>_<type>.log
ccbench lines from the mystery config (labs/lab2/sims/verilator/output).
"""
import re

from .common import (grouped_bars, latex_table, new_fig, parse_kv_colon, read, save,
                     sim_outputs, write_table, INK_MUTED, PALETTE)

ASSOC = [("CS152RocketConfig", 1), ("CS152RocketD2WayConfig", 2),
         ("CS152RocketD4WayConfig", 4), ("CS152RocketD8WayConfig", 8)]
RUNS = [("Naive", "CS152RocketConfig", "transpose-naive"),
        ("Blocked 8x8", "CS152RocketConfig", "transpose-blocked"),
        ("Blocked 8x8, L2 config", "CS152RocketL2Config", "transpose-blocked"),
        ("Two-level blocked, L2 config", "CS152RocketL2Config", "transpose-l2blocked")]
MYSTERY = "CS152RocketMysteryConfig"

_CCBENCH = re.compile(r"App:\[caches\].*?AppSize:\[(\d+)\],Time:\[([\d.]+)\].*?RunType:\[(\d+)\]")


def collect():
    data = {}
    for cfg, d in sim_outputs("lab2").items():
        for log in sorted(d.glob("*.log")):
            if log.name.endswith(".make.log"):
                continue
            text = read(log)
            if log.stem.startswith("caches_"):
                m = _CCBENCH.search(text)
                if m:
                    data.setdefault(cfg, {}).setdefault("ccbench", {})[m.group(1)] = float(m.group(2))
                continue
            stats = parse_kv_colon(text)
            if "cycles" in stats:
                stats["passed"] = "assert" not in text.lower()
                data.setdefault(cfg, {})[log.stem] = stats
    return data


def miss_rate(s):
    acc = s.get("loads", 0) + s.get("stores", 0)
    return s.get("d$ regular miss", 0) / acc if acc else float("nan")


def report(data):
    made = []

    runs = [(label, data[c][b]) for label, c, b in RUNS if b in data.get(c, {})]
    if runs:
        made.append(write_table("lab2", "transpose", latex_table(
            "Matrix transposition (L1 D\\$ miss rate = misses / (loads + stores))",
            ["Code / config", "Cycles", "Loads", "Stores", "D\\$ misses", "Miss rate"],
            [[label, s["cycles"], s.get("loads", ""), s.get("stores", ""),
              s.get("d$ regular miss", ""), f"{100 * miss_rate(s):.2f}\\%"] for label, s in runs])))
        fig, ax = new_fig()
        grouped_bars(ax, [l for l, _ in runs], {"cycles": [s["cycles"] for _, s in runs]}, value_fmt="{:,.0f}")
        ax.set_title("Transpose cycles"); ax.set_ylabel("Cycles")
        made.append(save(fig, "lab2", "transpose_cycles"))

    assoc = [(w, data[c]["transpose-blocked"]) for c, w in ASSOC if "transpose-blocked" in data.get(c, {})]
    if assoc:
        made.append(write_table("lab2", "3_5", latex_table(
            "$N$-Way Set Associativity vs. Miss Rate (4 KiB L1 D\\$, 8x8 blocked transpose)",
            ["$N$", "Miss Rate", "Cycles"],
            [[f"{w}-way", f"{100 * miss_rate(s):.2f}\\%", s["cycles"]] for w, s in assoc])))
        fig, ax = new_fig(figsize=(7, 4.2))
        ways = [w for w, _ in assoc]
        ax.plot(range(len(ways)), [100 * miss_rate(s) for _, s in assoc], marker="o",
                markersize=8, linewidth=2, color=PALETTE[0])
        for i, (_, s) in enumerate(assoc):
            ax.annotate(f"{100 * miss_rate(s):.1f}%", (i, 100 * miss_rate(s)), xytext=(0, 8),
                        textcoords="offset points", ha="center", fontsize=9, color=INK_MUTED)
        ax.set_xticks(range(len(ways)), [f"{w}-way" for w in ways])
        ax.set_title("L1 D$ miss rate vs associativity (capacity fixed at 4 KiB)")
        ax.set_ylabel("Miss rate (%)"); ax.set_ylim(bottom=0)
        made.append(save(fig, "lab2", "3_5"))

    cc = data.get(MYSTERY, {}).get("ccbench")
    if cc:
        sizes = sorted(int(s) for s in cc)
        kib = [4 * s / 1024 for s in sizes]
        fig, ax = new_fig(figsize=(8, 4.5))
        ax.plot(kib, [cc[str(s)] for s in sizes], marker="o", markersize=8, linewidth=2, color=PALETTE[0])
        ax.set_xscale("log", base=2)
        ax.set_xticks(kib, [f"{k:g}" for k in kib], rotation=45)
        ax.minorticks_off()
        ax.grid(True, axis="x", color="#e4e3de")
        ax.set_title(f"ccbench caches on {MYSTERY}")
        ax.set_xlabel("Array size (KiB)"); ax.set_ylabel("Cycles per iteration")
        made.append(save(fig, "lab2", "ccbench_mystery"))
        made.append(write_table("lab2", "ccbench_mystery", latex_table(
            "ccbench caches sweep on the mystery configuration",
            ["Elements", "Array size (KiB)", "Cycles / iteration"],
            [[s, f"{4 * s / 1024:g}", f"{cc[str(s)]:.2f}"] for s in sizes])))
    return made

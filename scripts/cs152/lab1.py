"""Lab 1 — Sodor pipelines.

Data: every <config>/<bench>.out commit trace + .log under labs/lab1/sims/verilator/output.
The trace pass reproduces riscv-sodor's scripts/tracer.py (same start condition,
same instruction categories via its instructions.py) and additionally counts the
load/store instructions with a non-zero immediate offset, which Problem 3.7
needs. The no-bypass 5-stage build appears as Sodor5StageConfig_nobypass.
"""
import re
import sys

from .common import (LABS, grouped_bars, latex_table, new_fig, parse_mcycle, read,
                     save, sim_outputs, write_table)

ORDER = ["dhrystone", "median", "multiply", "qsort", "rsort", "towers", "vvadd"]
PIPELINES = [("Sodor1StageConfig", "1-stage"), ("Sodor2StageConfig", "2-stage"),
             ("Sodor3StageConfig", "3-stage"), ("Sodor5StageConfig", "5-stage"),
             ("SodorUCodeConfig", "micro-coded")]
BYPASS, INTERLOCK = "Sodor5StageConfig", "Sodor5StageConfig_nobypass"

# Problem 3.7 counts loads/stores whose immediate offset is non-zero (each needs
# an extra addi). The original report's tracer only counted *positive* offsets;
# set this to False to reproduce its numbers exactly.
COUNT_NEGATIVE_OFFSETS = True

_TRACE = re.compile(r"Cyc=\s*(\d+) \[([01])\] pc=\[([0-9a-f]+)\].*?inst=\[([0-9a-f]+)\]")


def _sodor_isa():
    sys.path.insert(0, str(LABS / "lab1/generators/riscv-sodor/scripts"))
    import instructions as isa
    return isa


def _offset_counts(imm12):
    if imm12 & 0x800:                   # negative (sign bit of the 12-bit immediate)
        return COUNT_NEGATIVE_OFFSETS
    return imm12 != 0


def trace_stats(path, isa):
    """One pass over a Sodor commit trace (non-microcoded pipelines)."""
    decode = {}

    def category(word):
        if word not in decode:
            op = isa.Opcode.decode(word)
            if op in isa.BR_OPCODES:
                c = "branch"
            elif op in isa.JAL_OPCODES:
                c = "jump"
            elif op in isa.LD_OPCODES:
                c = "ld_nz" if _offset_counts(word >> 20) else "ld"
            elif op in isa.ST_OPCODES:
                c = "st_nz" if _offset_counts(((word >> 25) << 5) | ((word >> 7) & 0x1f)) else "st"
            elif op in isa.ARITH_OPCODES:
                c = "arith"
            else:
                c = "misc"
            decode[word] = c
        return decode[word]

    counts = dict.fromkeys(("branch", "jump", "ld", "ld_nz", "st", "st_nz", "arith", "misc"), 0)
    collecting, start, cycles, bubbles = False, 0, 0, 0
    with open(path, errors="replace") as f:
        for line in f:
            m = _TRACE.match(line)
            if not m:
                continue
            cyc, retire, pc = int(m.group(1)), m.group(2) == "1", int(m.group(3), 16)
            if retire and pc == 0x80000000:
                collecting, start = True, cyc
            if collecting:
                if retire:
                    counts[category(int(m.group(4), 16))] += 1
                else:
                    bubbles += 1
                cycles = cyc - start
    n = sum(counts.values())
    if n == 0:
        return {}
    ldst = counts["ld"] + counts["ld_nz"] + counts["st"] + counts["st_nz"]
    pct = lambda k: 100 * k / n
    return {
        "cycles": cycles, "instructions": n, "bubbles": bubbles,
        "cpi": cycles / n, "ipc": n / cycles if cycles else 0.0,
        "arithmetic": pct(counts["arith"]), "ldst": pct(ldst),
        "branch_jump": pct(counts["branch"] + counts["jump"]),
        "branch": pct(counts["branch"]), "jump": pct(counts["jump"]),
        "misc": pct(counts["misc"]),
        "ldst_nonzero_offset": counts["ld_nz"] + counts["st_nz"],
    }


def collect():
    isa = _sodor_isa()
    data = {}
    for cfg, d in sim_outputs("lab1").items():
        if "Sodor" not in cfg:
            continue
        for log in sorted(d.glob("*.log")):
            if log.name.endswith(".make.log"):
                continue
            bench = log.stem
            stats = parse_mcycle(read(log))
            out = log.with_suffix(".out")
            if "UCode" not in cfg and out.is_file():
                stats.update(trace_stats(out, isa))
            if stats:
                data.setdefault(cfg, {})[bench] = stats
    return data


def _benches(data, cfg):
    return [b for b in ORDER if b in data.get(cfg, {})]


def derived_cpi(m, w_mem):
    """Problem 3.5 model: memory ops cost w_mem cycles, branches/jumps and misc 1.5."""
    return (m["arithmetic"] + w_mem * m["ldst"] + 1.5 * m["branch_jump"]
            + 1.5 * m["misc"]) / 100 * m["cycles"] / m["instructions"]


def report(data):
    made = []
    s1 = "Sodor1StageConfig"
    bs = _benches(data, s1)
    bs = [b for b in bs if "arithmetic" in data[s1][b]]

    # 3.x — pipeline comparison on towers (benchmark-reported mcycle/minstret)
    pipes = [(c, n) for c, n in PIPELINES if "mcycle" in data.get(c, {}).get("towers", {})]
    if pipes:
        cpis = [data[c]["towers"]["mcycle"] / data[c]["towers"]["minstret"] for c, _ in pipes]
        fig, ax = new_fig()
        grouped_bars(ax, [n for _, n in pipes], {"towers": cpis}, value_fmt="{:.2f}")
        ax.set_title("towers CPI by pipeline"); ax.set_ylabel("CPI (mcycle / minstret)")
        made.append(save(fig, "lab1", "pipelines_towers"))
        made.append(write_table("lab1", "pipelines_towers", latex_table(
            "towers on each Sodor pipeline", ["Pipeline", "mcycle", "minstret", "CPI"],
            [[n, data[c]["towers"]["mcycle"], data[c]["towers"]["minstret"], f"{cpi:.3f}"]
             for (c, n), cpi in zip(pipes, cpis)])))

    if bs:
        # 3.4 — instruction breakdown
        fig, ax = new_fig()
        grouped_bars(ax, bs, {
            "Arithmetic": [data[s1][b]["arithmetic"] for b in bs],
            "Memory": [data[s1][b]["ldst"] for b in bs],
            "Control": [data[s1][b]["branch_jump"] for b in bs]})
        ax.set_title("Benchmark by instruction breakdown (1-stage)")
        ax.set_xlabel("Benchmark"); ax.set_ylabel("Share of instructions (%)")
        made.append(save(fig, "lab1", "3_4"))

        # 3.5 — derived CPIs
        cpi1 = [derived_cpi(data[s1][b], 2) for b in bs]
        cpi2 = [derived_cpi(data[s1][b], 1) for b in bs]
        for name, title, vals in (("3_5_1", "New CPI for benchmarks", cpi1),
                                  ("3_5_2", "New CPI for benchmarks (loads/stores at CPI 1)", cpi2)):
            fig, ax = new_fig()
            grouped_bars(ax, bs, {"CPI": vals}, value_fmt="{:.3f}")
            ax.set_title(title); ax.set_xlabel("Benchmark"); ax.set_ylabel("CPI")
            made.append(save(fig, "lab1", name))
            made.append(write_table("lab1", name, latex_table(
                title[0].upper() + title[1:], ["Benchmark", "CPI"],
                [[b, f"{c:.3f}"] for b, c in zip(bs, vals)])))
        fig, ax = new_fig()
        grouped_bars(ax, bs, {"Modified CPI": cpi1,
                              "Memory optimized, +30% cycle time": [c * 1.3 for c in cpi2]})
        ax.set_title("CPI comparison"); ax.set_xlabel("Benchmark"); ax.set_ylabel("CPI (normalized time)")
        made.append(save(fig, "lab1", "3_5_3"))

        # 3.7 — every non-zero-offset load/store needs an extra addi
        nz = {}
        for b in bs:
            m = data[s1][b]
            n, extra = m["instructions"], m["ldst_nonzero_offset"]
            new = n + extra
            nz[b] = {
                "instructions": new,
                "arithmetic": (m["arithmetic"] * n / 100 + extra) / new * 100,
                "ldst": m["ldst"] * n / new,
                "ldst_nonzero": extra / new * 100,
                "branch_jump": m["branch_jump"] * n / new,
                "misc": m["misc"] * n / new,
            }
        fig, ax = new_fig()
        grouped_bars(ax, bs, {
            "Arithmetic": [nz[b]["arithmetic"] for b in bs],
            "Memory": [nz[b]["ldst"] for b in bs],
            "Memory, non-zero offset": [nz[b]["ldst_nonzero"] for b in bs],
            "Control": [nz[b]["branch_jump"] for b in bs]})
        ax.set_title("Instruction breakdown with offset-free loads/stores")
        ax.set_xlabel("Benchmark"); ax.set_ylabel("Share of instructions (%)")
        made.append(save(fig, "lab1", "3_7_1"))
        fig, ax = new_fig()
        grouped_bars(ax, bs, {"Original": [data[s1][b]["instructions"] for b in bs],
                              "Offset-free loads/stores": [nz[b]["instructions"] for b in bs]})
        ax.set_title("Instruction count comparison"); ax.set_xlabel("Benchmark"); ax.set_ylabel("Instructions")
        made.append(save(fig, "lab1", "3_7_2"))
        made.append(write_table("lab1", "3_7", latex_table(
            "Effect of removing load/store offsets", ["Benchmark", "Instructions", "New instructions", "Increase",
                                                      "\\% Ld/St non-zero"],
            [[b, data[s1][b]["instructions"], nz[b]["instructions"],
              f"{nz[b]['instructions'] / data[s1][b]['instructions']:.4f}x", f"{nz[b]['ldst_nonzero']:.3f}"]
             for b in bs])))

    # 3.6 — full bypassing vs full interlocking on the 5-stage
    on_bs = [b for b in _benches(data, BYPASS) if "cpi" in data[BYPASS][b]
             and "cpi" in data.get(INTERLOCK, {}).get(b, {})]
    if on_bs:
        on = [data[BYPASS][b]["cpi"] for b in on_bs]
        off = [data[INTERLOCK][b]["cpi"] for b in on_bs]
        fig, ax = new_fig()
        grouped_bars(ax, on_bs, {"Full bypassing": on, "Full interlocking": off})
        ax.set_title("5-stage CPI: full bypassing vs full interlocking")
        ax.set_xlabel("Benchmark"); ax.set_ylabel("CPI")
        made.append(save(fig, "lab1", "3_6"))
        made.append(write_table("lab1", "3_6", latex_table(
            "5-stage CPI: bypassing vs interlocking",
            ["Benchmark", "CPI w/ Bypassing", "CPI w/ Interlocking", "Ratio"],
            [[b, f"{o:.3f}", f"{f:.3f}", f"{f / o:.3f}"] for b, o, f in zip(on_bs, on, off)])))

    # 4.1 — branch-heavy program
    br = data.get(s1, {}).get("branchy")
    if br and "arithmetic" in br:
        rows = [["Arithmetic", br["arithmetic"]], ["Ld/St", br["ldst"]],
                ["Branch/Jump", br["branch_jump"]], ["Branch", br["branch"]],
                ["Jump", br["jump"]], ["Misc.", br["misc"]]]
        cpi5 = data.get("Sodor5StageConfig", {}).get("branchy", {}).get("cpi")
        made.append(write_table("lab1", "4_1", latex_table(
            "Instruction breakdown of the branch-heavy program"
            + (f" (5-stage CPI {cpi5:.3f})" if cpi5 else ""),
            ["Type", "Percentage"], [[t, f"{v:.3f}"] for t, v in rows])))
    return made

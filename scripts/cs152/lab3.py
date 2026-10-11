"""Lab 3 — BOOM.

Data: <bench>.log (mcycle/minstret) and <bench>.out (branch-predictor summary
appended by BOOM's bpd script) per config under labs/lab3/sims/verilator/output.
"""
import re

from .common import grouped_bars, latex_table, new_fig, parse_mcycle, read, save, sim_outputs, write_table

ORDER = ["dhrystone", "median", "multiply", "qsort", "spmv", "towers", "vvadd"]

# In-order Rocket CPIs are given in the Lab 3 handout (Problem 3.3 table).
ROCKET_PROVIDED = {"dhrystone": 1.200, "median": 1.379, "multiply": 1.136, "qsort": 1.427,
                   "spmv": 1.690, "towers": 1.029, "vvadd": 1.024}

SWEEP = [("CS152BaselineBoomConfig", "BOOM (worst-case)"), ("CS152BoomPRF64Config", "BOOM (64 PRF)"),
         ("CS152BoomROB16Config", "BOOM (16 ROB)"), ("CS152BoomBrPredConfig", "BOOM (br. pred.)")]
PREDICTORS = [("CS152SWPredBoomConfig", "BOOM (base configuration)"),
              ("CS152SWPredBoomConfig_custom", "BOOM (custom branch prediction)")]

_MISPRED = re.compile(r"Mispredicted (\d+)/([\d.]+) all, ([\d.]+)")


def collect():
    data = {}
    for cfg, d in sim_outputs("lab3").items():
        for log in sorted(d.glob("*.log")):
            if log.name.endswith(".make.log"):
                continue
            stats = parse_mcycle(read(log))
            if not stats:
                continue
            stats["cpi"] = stats["mcycle"] / stats["minstret"]
            stats["ipc"] = stats["minstret"] / stats["mcycle"]
            out = log.with_suffix(".out")
            # the summary is at the very end of a potentially large file
            tail = _tail(out)
            m = _MISPRED.search(tail)
            if m:
                stats["mispredicted"] = int(m.group(1))
                stats["branches"] = int(float(m.group(2)))
                stats["mispredict_rate"] = float(m.group(3))
            data.setdefault(cfg, {})[log.stem] = stats
    return data


def _tail(path, size=8192):
    try:
        with open(path, "rb") as f:
            f.seek(0, 2)
            f.seek(max(0, f.tell() - size))
            return f.read().decode(errors="replace")
    except OSError:
        return ""


def _row_table(caption, rows, benches, fmt="{:.3f}"):
    return latex_table(caption, [""] + benches,
                       [[label] + [fmt.format(v) if v is not None else "--" for v in vals]
                        for label, vals in rows])


def report(data):
    made = []
    sweep = [(c, l) for c, l in SWEEP if c in data]
    if sweep:
        benches = [b for b in ORDER if any(b in data[c] for c, _ in sweep)]
        cpi_rows = [("Rocket (provided)", [ROCKET_PROVIDED.get(b) for b in benches])]
        cpi_rows += [(l, [data[c].get(b, {}).get("cpi") for b in benches]) for c, l in sweep]
        made.append(write_table("lab3", "3_3_cpi", _row_table("CPI for Different Optimizations", cpi_rows, benches)))
        fig, ax = new_fig()
        grouped_bars(ax, benches, dict(cpi_rows))
        ax.set_title("CPI: Rocket vs cumulative BOOM improvements"); ax.set_ylabel("CPI")
        made.append(save(fig, "lab3", "3_3_cpi"))

        mp_rows = [(l, [data[c].get(b, {}).get("mispredict_rate") for b in benches]) for c, l in sweep]
        made.append(write_table("lab3", "3_3_mispredict",
                                _row_table("Branch Misprediction Rates", mp_rows, benches)))
        fig, ax = new_fig()
        grouped_bars(ax, benches, dict(mp_rows))
        ax.set_title("Branch misprediction rate"); ax.set_ylabel("Mispredicted / branches")
        made.append(save(fig, "lab3", "3_3_mispredict"))

    preds = [(c, l) for c, l in PREDICTORS if c in data]
    if preds:
        benches = [b for b in ORDER if any(b in data[c] for c, _ in preds)]
        for key, name, title, ylabel in (("ipc", "4_1_ipc", "IPC", "IPC"),
                                         ("mispredict_rate", "4_1_mispredict",
                                          "Branch Misprediction Rates", "Mispredicted / branches")):
            rows = [(l, [data[c].get(b, {}).get(key) for b in benches]) for c, l in preds]
            made.append(write_table("lab3", name, _row_table(title, rows, benches)))
            fig, ax = new_fig()
            grouped_bars(ax, benches, dict(rows))
            ax.set_title(f"{title}: stock bimodal vs custom predictor"); ax.set_ylabel(ylabel)
            made.append(save(fig, "lab3", name))
    return made

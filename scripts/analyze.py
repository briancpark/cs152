#!/usr/bin/env python3
"""
analyze.py — parse CS152 simulator output and regenerate report figures/tables.

For each lab it collects whatever simulator output exists, writes the parsed
data to results/<lab>.json, and renders figures to latex/figures/<lab>/ and
LaTeX tables to latex/tables/<lab>/.

If a lab has no simulator output on this machine (e.g. a fresh clone), the
committed results/<lab>.json is used instead, so figures can always be rebuilt
with only python3 + matplotlib.

Usage:
    scripts/analyze.py                 # all labs
    scripts/analyze.py lab1 lab3
    scripts/analyze.py --from-json     # never read simulator output
"""
import argparse
import sys

from cs152 import common, lab1, lab2, lab3, lab4, lab5

LABS = {"lab1": lab1, "lab2": lab2, "lab3": lab3, "lab4": lab4, "lab5": lab5}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("labs", nargs="*", help="labs to analyze (default: all)")
    ap.add_argument("--from-json", action="store_true", help="only use committed results/<lab>.json")
    args = ap.parse_args()
    bad = [l for l in args.labs if l not in LABS]
    if bad:
        ap.error(f"unknown lab(s): {' '.join(bad)}")

    status = 0
    for name in args.labs or LABS:
        mod = LABS[name]
        data = None if args.from_json else mod.collect()
        if data:
            print(f"[ok] {name}: parsed simulator output -> {common.rel(common.write_json(name, data))}")
        else:
            data = common.load_json(name)
            if not data:
                print(f"[warn] {name}: no simulator output and no results/{name}.json "
                      f"(run ./run_labs.sh {name})", file=sys.stderr)
                status = 1
                continue
            print(f"[ok] {name}: using committed results/{name}.json")
        made = mod.report(data)
        for p in made:
            print(f"     {common.rel(p)}")
        if not made:
            print(f"[warn] {name}: data present but nothing to plot yet", file=sys.stderr)
    return status


if __name__ == "__main__":
    sys.exit(main())

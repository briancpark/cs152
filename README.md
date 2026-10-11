# CS 152

CS 152 is Computer Architecture and Engineering at UC Berkeley. I took this offering in Spring 2022 under John Wawrzynek. This repo contains my development setup and notes.

## Layout

| Path | What |
|---|---|
| `labs/lab{1..5}` | Lab repos (submodules). Labs 1, 2, 3 and 5 are Chipyard trees; lab 4 is RVV benchmarks for Spike. |
| `latex/` | Homework and lab reports. `make` builds the PDFs. |
| `run_labs.sh` | Builds the simulators and runs every experiment the lab reports use. |
| `scripts/analyze.py` | Parses simulator output into `results/<lab>.json` and renders `latex/figures/<lab>/` and `latex/tables/<lab>/`. |
| `scripts/overlays/` | Extra files the runner puts into the lab trees: configs the labs had you hand-edit, code variants from the reports, toolchain workarounds. |
| `results/` | Parsed data, committed so figures can be rebuilt without simulators. |

## Reproducing the lab results

```sh
git clone --recursive git@github.com:briancpark/cs152.git && cd cs152
./run_labs.sh check          # lists any missing prerequisites
./run_labs.sh all            # or lab1 ... lab5; resumable, FORCE=1 re-runs everything
cd latex && make
```

Prerequisites: Spike and spike-dasm in `$RISCV/bin` (default `/opt/riscv`), any bare-metal `riscv64-unknown-elf-gcc`, JDK 11, Verilator, `dtc`, and Python 3 with matplotlib and numpy. See `.github/workflows/chipyard-labs.yml` for install steps and for the selective submodule init the Chipyard labs need.

To rebuild only the figures and tables from the committed data (needs only Python):

```sh
./run_labs.sh analyze        # or: python3 scripts/analyze.py [labN ...]
```

### What each lab runs

| Lab | Simulators | Experiments → outputs |
|---|---|---|
| 1 | Sodor 1/2/3/5-stage and micro-coded, plus 5-stage with bypassing off | towers on every pipeline; full suite traced on 1-stage (3.4, 3.5, 3.7) and on 5-stage with and without bypassing (3.6); branch-heavy program (4.1) |
| 2 | Rocket at 1/2/4/8-way (4 KiB), L2, mystery | naive, 8×8 blocked and two-level blocked transpose (3.3–3.6); ccbench cache sweep (4.1) |
| 3 | BOOM worst case → +64 PRF → +16 ROB → +branch prediction; SW predictor, stock and custom | CPI and misprediction tables (3.3); IPC and misprediction, stock vs custom predictor (4.1) |
| 4 | Spike | scalar vs vector instruction counts and cache stats |
| 5 | dual Rocket, MI / MSI / MESI | mt-vvadd and mt-matmul, naive vs optimized |

### Differences from the original course environment

- **Toolchain.** Berkeley's `riscv64-unknown-elf` toolchain is replaced by a stock bare-metal GCC. The runner builds libgloss-htif from each lab's vendored source, and builds the riscv-tests benchmarks against the freestanding riscv-tests env. Cycle counts differ slightly from the course machines; behavior is the same.
- **Lab 5 TLS.** The barrier in `lab/common/util.c` uses `__thread`. A GCC built with `--disable-tls` turns that into a single shared variable and the barrier deadlocks, so the runner uses a per-hart copy (`scripts/overlays/lab5/util.c`).
- **Lab 4 timing.** The course's Spike had a timing model. Stock Spike reports `mcycle == minstret`, so lab 4 compares instruction counts and cache statistics, not cycles.
- **Lab 1, Problem 3.7.** Every load or store with a non-zero immediate offset is counted. The original report counted only positive offsets; set `COUNT_NEGATIVE_OFFSETS = False` in `scripts/cs152/lab1.py` to reproduce its numbers.
- **Lab 3.** The Rocket CPI row comes from the handout, as in the original lab.

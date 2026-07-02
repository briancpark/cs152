#!/usr/bin/env bash
#
# run_labs.sh — build and run the CS152 labs locally.
#
# This reproduces the commands recorded in each lab's logs.md / log.md and the
# .github/workflows/*.yml CI flows, adapted to this machine:
#   * RISC-V tools (spike, spike-dasm, elf2hex) are installed at /opt/riscv
#   * A bare-metal gcc is at /usr/local/bin/riscv64-unknown-elf-gcc
#   * The Chipyard sbt/Scala stack needs JDK 11 (JDK 21 breaks the old sbt)
#
# Submodules are already initialized; we only (re)build simulators and run binaries.
#
# Usage:
#   ./run_labs.sh lab1|lab2|lab3|lab4|lab5|all
#   ./run_labs.sh                # defaults to "all"
#   ./run_labs.sh analyze        # re-parse existing output -> results/ + figures
#
# Running a lab also parses its output into results/<lab>.{json,csv},
# results/tables/<lab>.tex, and results/figures/<lab>/*.png (see scripts/).
#
# Override the environment if your install differs, e.g.:
#   RISCV=/my/riscv JAVA11_HOME=/path/to/jdk11 ./run_labs.sh lab1
#
set -uo pipefail

# ----------------------------------------------------------------------------
# Configuration (override via environment)
# ----------------------------------------------------------------------------
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LABS_DIR="$REPO_ROOT/labs"
RISCV="${RISCV:-/opt/riscv}"
JAVA11_HOME="${JAVA11_HOME:-/usr/lib/jvm/java-11-openjdk-amd64}"
JOBS="${JOBS:-$(nproc)}"

JFLAG="-j${JOBS}"

log()  { printf '\n\033[1;34m==> %s\033[0m\n' "$*"; }
ok()   { printf '\033[1;32m[OK]\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m[WARN]\033[0m %s\n' "$*"; }
die()  { printf '\033[1;31m[ERROR]\033[0m %s\n' "$*" >&2; exit 1; }

# ----------------------------------------------------------------------------
# Environment setup
# ----------------------------------------------------------------------------
setup_env() {
  [ -d "$RISCV/bin" ] || die "RISCV toolchain not found at $RISCV (set RISCV=...)"
  command -v "$RISCV/bin/spike-dasm" >/dev/null 2>&1 || warn "spike-dasm not under $RISCV/bin"
  export RISCV
  # Chipyard labs need JDK 11; lab4 only needs the riscv tools.
  if [ -x "$JAVA11_HOME/bin/java" ]; then
    export JAVA_HOME="$JAVA11_HOME"
    export PATH="$JAVA_HOME/bin:$RISCV/bin:$PATH"
  else
    warn "JDK 11 not found at $JAVA11_HOME — Chipyard labs (1,2,3,5) will fail; lab4 still works."
    export PATH="$RISCV/bin:$PATH"
  fi
}

# Apply the build fixes the CI workflow applies, but only when needed (idempotent).
# Old Chipyard + modern JDK/Verilator/GCC require these tweaks.
fix_chipyard_build() {
  local root="$1"
  # 1. Drop -XX:MaxPermSize (removed in JDK 8+, fatal on JDK 11+)
  if grep -q 'XX:MaxPermSize' "$root/variables.mk" 2>/dev/null; then
    sed -i 's/ -XX:MaxPermSize=256M//g' "$root/variables.mk"
    ok "removed MaxPermSize from $(basename "$root")/variables.mk"
  fi
  # 2. Verilator >= 5 needs --no-timing for these designs
  if [ -f "$root/sims/verilator/Makefile" ] && \
     grep -q 'VERILATOR := verilator --cc --exe$' "$root/sims/verilator/Makefile"; then
    sed -i 's/VERILATOR := verilator --cc --exe$/VERILATOR := verilator --cc --exe --no-timing/' \
      "$root/sims/verilator/Makefile"
    ok "added --no-timing to $(basename "$root") Verilator flags"
  fi
  # 3. Modern g++ rejects C++11 for the generated harness; bump to C++17
  for f in "$root/sims/common-sim-flags.mk" "$root/sims/verilator/Makefile" "$root/variables.mk"; do
    if [ -f "$f" ] && grep -q 'std=c++11' "$f"; then
      sed -i 's/-std=c++11/-std=c++17/g' "$f"
      ok "bumped C++ standard to c++17 in $(basename "$root")/$(basename "$f")"
    fi
  done
}

# Build one Chipyard verilator simulator, with the workflow's PCH workaround.
build_chipyard_sim() {
  local root="$1" cfg="$2"
  local sim="$root/sims/verilator/simulator-chipyard-$cfg"
  if [ -x "$sim" ]; then ok "already built: $cfg"; return 0; fi
  log "Building $cfg (this takes several minutes)"
  ( cd "$root/sims/verilator" && make CONFIG="$cfg" "$JFLAG" )
  if [ ! -x "$sim" ]; then
    # Verilator precompiled-header race seen on some versions; seed and retry.
    local bd="$root/sims/verilator/generated-src/chipyard.TestHarness.$cfg/chipyard.TestHarness.$cfg"
    if [ -d "$bd" ] && [ ! -f "$bd/VTestHarness__pch.h.fast" ]; then
      warn "applying PCH workaround for $cfg"
      printf '#include "VTestHarness__pch.h"\n' > "$bd/VTestHarness__pch.h.fast"
      printf '#include "VTestHarness__pch.h"\n' > "$bd/VTestHarness__pch.h.slow"
      ( cd "$root/sims/verilator" && make CONFIG="$cfg" "$JFLAG" )
    fi
  fi
  [ -x "$sim" ] && ok "built $cfg" || die "build failed: $cfg"
}

# ----------------------------------------------------------------------------
# RISC-V bare-metal test-binary toolchain (labs 2 & 3)
#
# The directed tests / benchmarks are normally built on Berkeley's cluster with
# a riscv64-unknown-elf toolchain that bundled libgloss-htif. This machine's
# xpack toolchain lacks a working htif.ld/specs combo, so we build the binaries
# directly against the riscv-tests freestanding htif env that ships in the
# submodule (crt.S + syscalls.c + test.ld), plus a few newlib-compat stubs.
# Note: compiled with xpack gcc 14, so cycle/instret counts differ slightly
# from the Berkeley-built numbers in the lab logs — behaviour is equivalent.
# ----------------------------------------------------------------------------
HTIF_STUBS="$REPO_ROOT/scripts/htif_stubs.c"

# Initialize the riscv-tests `env` nested submodule (provides encoding.h).
ensure_rvtest_env() {
  local rt="$1"
  if [ ! -f "$rt/env/encoding.h" ]; then
    log "Initializing riscv-tests env submodule"
    ( cd "$rt" && git submodule update --init env ) || warn "env submodule init failed"
  fi
}

# build_htif_binary <out.riscv> <riscv-tests-root> <extra-cflags> <include-dir> <src...>
build_htif_binary() {
  local out="$1" rt="$2" extra="$3" incdir="$4"; shift 4
  local common="$rt/benchmarks/common"
  # shellcheck disable=SC2086
  riscv64-unknown-elf-gcc -mcmodel=medany -march=rv64gc_zicsr_zifencei -mabi=lp64d \
    -static -O2 -ffast-math -fno-common -fno-builtin-printf -nostdlib -nostartfiles \
    $extra -I"$rt/env" -I"$common" -I"$incdir" \
    -o "$out" "$@" "$common/syscalls.c" "$common/crt.S" "$HTIF_STUBS" \
    -T "$common/test.ld" -lm -lgcc 2>&1 | grep -v 'RWX permissions'
  [ -x "$out" ]
}

# ----------------------------------------------------------------------------
# Lab 1 — Sodor pipelines (commands from labs/lab1/logs.md)
# ----------------------------------------------------------------------------
lab1() {
  local ROOT="$LABS_DIR/lab1"
  [ -d "$ROOT" ] || die "lab1 not found"
  fix_chipyard_build "$ROOT"
  local BMARKS="$ROOT/generators/riscv-sodor/riscv-bmarks"
  local SCRIPTS="$ROOT/generators/riscv-sodor/scripts"
  local CONFIGS="Sodor1StageConfig Sodor2StageConfig Sodor3StageConfig Sodor5StageConfig SodorUCodeConfig"
  local SUITE="dhrystone median multiply qsort rsort towers vvadd"

  for cfg in $CONFIGS; do build_chipyard_sim "$ROOT" "$cfg"; done

  log "Lab1: towers across all pipeline configs"
  for cfg in $CONFIGS; do
    printf -- '--- %s : towers ---\n' "$cfg"
    ( cd "$ROOT/sims/verilator" && \
      make CONFIG="$cfg" run-binary BINARY="$BMARKS/towers.riscv" 2>&1 ) \
      | grep -E 'mcycle|minstret|PASSED|FAILED'
  done

  for cfg in Sodor1StageConfig Sodor5StageConfig; do
    log "Lab1: CPI analysis on $cfg"
    for b in $SUITE; do
      printf -- '--- %s : %s ---\n' "$cfg" "$b"
      ( cd "$ROOT/sims/verilator" && \
        make CONFIG="$cfg" run-binary BINARY="$BMARKS/$b.riscv" 2>&1 ) \
        | grep -E 'mcycle|minstret|PASSED|FAILED'
      local out="$ROOT/sims/verilator/output/chipyard.TestHarness.$cfg/$b.out"
      [ -f "$out" ] && python3 "$SCRIPTS/tracer.py" "$out" 2>&1 \
        | grep -E 'CPI|IPC|Cycles|Instructions|Bubbles|Arithmetic|Ld/St|Branch|Misc'
    done
  done
  ok "lab1 complete"
}

# ----------------------------------------------------------------------------
# Lab 2 — Rocket caches (commands from labs/lab2/log.md)
# ----------------------------------------------------------------------------
lab2() {
  local ROOT="$LABS_DIR/lab2"
  [ -d "$ROOT" ] || die "lab2 not found"
  fix_chipyard_build "$ROOT"
  local TESTDIR="$ROOT/lab/directed"

  local RT="$ROOT/toolchains/riscv-tools/riscv-tests"
  build_chipyard_sim "$ROOT" "CS152RocketConfig"
  build_chipyard_sim "$ROOT" "CS152RocketL2Config"

  # The directed Makefile uses -specs=htif_nano.specs (missing here); build
  # transpose against the riscv-tests htif env instead. <assert.h>/fputs need
  # the stubs in scripts/htif_stubs.c.
  ensure_rvtest_env "$RT"
  log "Lab2: build directed transpose test"
  if build_htif_binary "$TESTDIR/transpose.riscv" "$RT" "-std=gnu11" "$TESTDIR" \
       "$TESTDIR/transpose.c" "$TESTDIR/trap.c"; then
    ok "built transpose.riscv"
  else
    warn "transpose build failed; skipping runs"; return
  fi

  for cfg in CS152RocketConfig CS152RocketL2Config; do
    log "Lab2: run transpose on $cfg"
    ( cd "$ROOT/sims/verilator" && \
      make CONFIG="$cfg" run-binary-hex BINARY="$TESTDIR/transpose.riscv" 2>&1 ) \
      | grep -E 'cycles|instret|miss|release|branches|mispredicts|interlock|blocked|PASSED|FAILED'
  done
  ok "lab2 complete"
}

# ----------------------------------------------------------------------------
# Lab 3 — BOOM (commands from labs/lab3/log.md)
# ----------------------------------------------------------------------------
lab3() {
  local ROOT="$LABS_DIR/lab3"
  [ -d "$ROOT" ] || die "lab3 not found"
  fix_chipyard_build "$ROOT"
  build_chipyard_sim "$ROOT" "CS152BaselineBoomConfig"

  # chipyard's run-bmark-tests expects prebuilt binaries under
  # $RISCV/.../share/riscv-tests (not installed here), so build the riscv-tests
  # benchmarks from the submodule and run each via run-binary. dhrystone is K&R
  # C, so allow the legacy-C downgrades.
  local RT="$ROOT/toolchains/riscv-tools/riscv-tests"
  ensure_rvtest_env "$RT"
  local OUT="$ROOT/sims/verilator/lab3-bmarks"; mkdir -p "$OUT"
  local PERMISSIVE="-Wno-implicit-int -Wno-implicit-function-declaration -fpermissive"
  local BMARKS="median multiply qsort towers vvadd dhrystone mm spmv mt-matmul mt-vvadd"

  log "Lab3: build riscv-tests benchmarks"
  local built=""
  for bm in $BMARKS; do
    local dir="$RT/benchmarks/$bm"
    [ -d "$dir" ] || { warn "no source for $bm"; continue; }
    if build_htif_binary "$OUT/$bm.riscv" "$RT" "-std=gnu99 $PERMISSIVE" "$dir" $dir/*.c >/dev/null 2>&1; then
      built="$built $bm"; ok "built $bm"
    else
      warn "build failed: $bm"
    fi
  done

  for bm in $built; do
    log "Lab3: run $bm on CS152BaselineBoomConfig"
    ( cd "$ROOT/sims/verilator" && \
      make CONFIG=CS152BaselineBoomConfig run-binary BINARY="$OUT/$bm.riscv" 2>&1 ) \
      | grep -E 'mcycle|minstret|PASSED|FAILED|Completed|Mflops|Dhrystone'
  done
  ok "lab3 complete"
}

# ----------------------------------------------------------------------------
# Lab 4 — RISC-V vector assembly (commands from .github/workflows/lab4.yml)
# ----------------------------------------------------------------------------
lab4() {
  local ROOT="$LABS_DIR/lab4"
  local BM="$ROOT/benchmarks"
  [ -d "$BM" ] || die "lab4 benchmarks not found"
  command -v "$RISCV/bin/spike" >/dev/null 2>&1 || die "spike not found under $RISCV/bin"

  # Toolchain-compat fixes (idempotent — already applied in this tree).
  if grep -q 'zvlsseg\|--varch\|--ic=64:4:64:16' "$BM/Makefile" 2>/dev/null; then
    log "Lab4: patching Makefile for the modern toolchain/Spike"
    sed -i 's/-Wa,-march=rv64gcv_zvlsseg/-march=rv64gcv_zicsr_zifencei -mabi=lp64d/g' "$BM/Makefile"
    sed -i 's/--varch=vlen:512,elen:64,dlen:128 //g; s/--br=3:28:512:6 //g' "$BM/Makefile"
    sed -i 's/--ic=64:4:64:16/--ic=64:4:64/g; s/--dc=64:4:64:16/--dc=64:4:64/g; s/--l2=1024:8:64:58/--l2=1024:8:64/g' "$BM/Makefile"
  fi
  if [ ! -f "$BM/common/malloc_stub.c" ]; then
    log "Lab4: adding bare-metal malloc stub"
    cat > "$BM/common/malloc_stub.c" <<'STUB'
#include <stddef.h>
extern char _end[];
static char *heap_ptr = 0;
void *malloc(size_t size){ if(!heap_ptr) heap_ptr=_end; void*p=heap_ptr; heap_ptr+=(size+7)&~7; return p; }
void free(void *p){ (void)p; }
void *calloc(size_t n,size_t s){ size_t t=n*s; char*p=malloc(t); for(size_t i=0;i<t;i++)p[i]=0; return p; }
void *realloc(void *p,size_t s){ (void)p; return malloc(s); }
STUB
  fi

  log "Lab4: compile all benchmarks"
  ( cd "$BM" && make "$JFLAG" ) || warn "benchmark build reported errors"

  # Save each run's stdout (where `mcycle = N` is printed) to <bench>.result so
  # parse_results.py can harvest it (spike's own .riscv.out captures only the
  # stderr commit-log).
  log "Lab4: run scalar benchmarks on Spike"
  for b in csaxpy cmplxmult dgemv dgemm imax spmv rsort; do
    [ -f "$BM/$b.riscv" ] || { warn "missing $b.riscv"; continue; }
    printf -- '--- %s ---\n' "$b"
    spike --isa=rv64gcv --ic=64:4:64 --dc=64:4:64 --l2=1024:8:64 "$BM/$b.riscv" \
      2>/dev/null | tee "$BM/$b.result" | head -8
  done

  log "Lab4: run vector benchmarks on Spike"
  for b in vec-csaxpy vec-cmplxmult vec-dgemv vec-dgemm; do
    [ -f "$BM/$b.riscv" ] || { warn "missing $b.riscv"; continue; }
    printf -- '--- %s ---\n' "$b"
    spike --isa=rv64gcv --ic=64:4:64 --dc=64:4:64 --l2=1024:8:64 "$BM/$b.riscv" \
      2>/dev/null | tee "$BM/$b.result" | head -8
  done
  ok "lab4 complete"
}

# ----------------------------------------------------------------------------
# Lab 5 — Cache coherence, dual Rocket MSI (config from labs/lab5 CS152Configs)
# ----------------------------------------------------------------------------
lab5() {
  local ROOT="$LABS_DIR/lab5"
  [ -d "$ROOT" ] || die "lab5 not found"
  fix_chipyard_build "$ROOT"
  # Build all four coherence-protocol configs the lab studies.
  for cfg in Lab5MSIDualRocketConfig Lab5MESIDualRocketConfig Lab5MIDualRocketConfig Lab5RocketConfig; do
    build_chipyard_sim "$ROOT" "$cfg"
  done

  ok "lab5 simulators built: $(ls "$ROOT"/sims/verilator/simulator-chipyard-Lab5*Config 2>/dev/null | wc -l) configs"
  warn "Lab5 multithreaded tests (mt-vvadd/mt-matmul) are NOT auto-run here."
  cat <<'NOTE'
    The lab5 lab/ tests are multithreaded and depend on a native-TLS htif
    runtime (a global `nharts`, __thread storage) that Berkeley's
    riscv64-unknown-elf toolchain provided. This machine's xpack gcc defaults to
    *emulated* TLS, which is incompatible with riscv-tests' crt.S TLS init, and
    lab5/lab/common ships no crt.S/syscalls.c of its own. Running these tests
    needs the Berkeley riscv-gnu-toolchain (native TLS) built into $RISCV.
    The simulators themselves are built and verified above.
NOTE
  ok "lab5 complete (simulators built; see note on test binaries)"
}

# ----------------------------------------------------------------------------
# Analysis — parse simulator output into data, then regenerate figures/tables
# ----------------------------------------------------------------------------
analyze() {
  command -v python3 >/dev/null 2>&1 || { warn "python3 not found; skipping analysis"; return; }
  local labs="$*"
  log "Analyze: parsing results -> results/*.json,.csv, tables/*.tex"
  python3 "$REPO_ROOT/scripts/parse_results.py" $labs || warn "parse step had warnings"
  log "Analyze: generating figures -> results/figures/"
  python3 "$REPO_ROOT/scripts/plot_results.py" $labs || warn "plot step had warnings"
  # Regenerate the exact report figures + LaTeX tables lab1.tex consumes.
  if [ -z "$labs" ] || printf '%s\n' $labs | grep -qx lab1; then
    if [ -f "$REPO_ROOT/results/lab1.json" ]; then
      log "Analyze: regenerating lab1 report figures/tables (3_4..3_6) -> latex/figures/"
      python3 "$REPO_ROOT/scripts/gen_lab1_figures.py" || warn "lab1 report gen had warnings"
    fi
  fi
}

# ----------------------------------------------------------------------------
# Dispatch
# ----------------------------------------------------------------------------
main() {
  local target="${1:-all}"
  setup_env
  log "RISCV=$RISCV  JAVA_HOME=${JAVA_HOME:-<none>}  JOBS=$JOBS"
  case "$target" in
    lab1) lab1; analyze lab1 ;;
    lab2) lab2; analyze lab2 ;;
    lab3) lab3 ;;                            # lab3 metrics not yet wired into analyze
    lab4) lab4; analyze lab4 ;;
    lab5) lab5 ;;
    all)  lab4; lab1; lab2; lab3; lab5; analyze ;;
    analyze|plots) analyze ;;               # re-parse + re-plot existing outputs only
    *)    die "unknown target '$target' (use: lab1|lab2|lab3|lab4|lab5|all|analyze)" ;;
  esac
  log "Done: $target"
}

main "$@"

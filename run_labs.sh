#!/usr/bin/env bash
#
# run_labs.sh — build and run every CS152 lab experiment locally, then
# regenerate the report figures/tables from the simulator output.
#
# Each lab function builds the simulators its report needs (including design
# points the original lab had you hand-edit between builds — those come from
# scripts/overlays/), builds the test binaries, and runs the full experiment
# matrix. scripts/analyze.py then turns the output into
#   results/<lab>.json                    parsed data (commit this)
#   latex/figures/<lab>/*.png             report figures
#   latex/tables/<lab>/*.tex              report tables (\input-able)
#
# Usage:
#   ./run_labs.sh [lab1|lab2|lab3|lab4|lab5|all]   build + run + analyze (default: all)
#   ./run_labs.sh analyze [labN ...]               re-analyze existing output only
#   ./run_labs.sh check                            report missing prerequisites
#
# Runs are resumable: a finished run leaves a .done stamp next to its log and is
# skipped next time. FORCE=1 re-runs everything.
#
# Environment overrides:
#   RISCV=/opt/riscv            spike, spike-dasm, elf2hex
#   JAVA11_HOME=...             JDK 11 for the old sbt/Chisel stack
#   JOBS=$(nproc)               make -j for simulator builds
#   PAR=$(nproc)/2              simulations run concurrently
#   FORCE=1                     ignore .done stamps
#
set -uo pipefail

# ----------------------------------------------------------------------------
# Configuration
# ----------------------------------------------------------------------------
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LABS_DIR="$REPO_ROOT/labs"
BUILD_DIR="$REPO_ROOT/build"            # toolchain bits + test binaries (gitignored)
OVERLAYS="$REPO_ROOT/scripts/overlays"
RISCV="${RISCV:-/opt/riscv}"
JAVA11_HOME="${JAVA11_HOME:-/usr/lib/jvm/java-11-openjdk-amd64}"
JOBS="${JOBS:-$(nproc)}"
PAR="${PAR:-$(( $(nproc) / 2 > 0 ? $(nproc) / 2 : 1 ))}"
FORCE="${FORCE:-}"
export FORCE

RV64_ARCH="-march=rv64gc_zicsr_zifencei -mabi=lp64d"

log()  { printf '\n\033[1;34m==> %s\033[0m\n' "$*"; }
ok()   { printf '\033[1;32m[OK]\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m[WARN]\033[0m %s\n' "$*"; }
die()  { printf '\033[1;31m[ERROR]\033[0m %s\n' "$*" >&2; exit 1; }

# ----------------------------------------------------------------------------
# Environment
# ----------------------------------------------------------------------------
setup_env() {
  [ -d "$RISCV/bin" ] || die "RISCV toolchain not found at $RISCV (set RISCV=..., or run ./run_labs.sh check)"
  command -v riscv64-unknown-elf-gcc >/dev/null 2>&1 || die "riscv64-unknown-elf-gcc not on PATH"
  export RISCV
  if [ -x "$JAVA11_HOME/bin/java" ]; then
    export JAVA_HOME="$JAVA11_HOME"
    export PATH="$JAVA_HOME/bin:$RISCV/bin:$PATH"
  else
    warn "JDK 11 not found at $JAVA11_HOME — Chipyard labs (1,2,3,5) will fail; lab4 still works."
    export PATH="$RISCV/bin:$PATH"
  fi
  mkdir -p "$BUILD_DIR"
}

check() {
  local miss=0
  chk() { if eval "$2" >/dev/null 2>&1; then ok "$1"; else warn "missing: $1  ($3)"; miss=1; fi; }
  chk "RISC-V tools in $RISCV/bin"        "[ -x '$RISCV/bin/spike' ] && [ -x '$RISCV/bin/spike-dasm' ]" "build riscv-isa-sim into \$RISCV"
  chk "riscv64-unknown-elf-gcc"           "command -v riscv64-unknown-elf-gcc"  "any bare-metal RISC-V GCC (xPack works)"
  chk "JDK 11 at $JAVA11_HOME"            "[ -x '$JAVA11_HOME/bin/java' ]"      "apt install openjdk-11-jdk-headless"
  chk "verilator"                         "command -v verilator"                "apt install verilator"
  chk "dtc"                               "command -v dtc"                      "apt install device-tree-compiler"
  chk "python3 + matplotlib + numpy"      "python3 -c 'import matplotlib, numpy'" "pip install matplotlib numpy"
  for l in 1 2 3 4 5; do
    chk "labs/lab$l submodule"            "[ -n \"\$(ls -A '$LABS_DIR/lab$l' 2>/dev/null)\" ]" "git submodule update --init labs/lab$l (Chipyard labs then need their own submodules; see .github/workflows/chipyard-labs.yml)"
  done
  return $miss
}

# ----------------------------------------------------------------------------
# Chipyard helpers
# ----------------------------------------------------------------------------

# Old Chipyard + modern JDK/Verilator/GCC need these tweaks (idempotent).
fix_chipyard_build() {
  local root="$1"
  # sbt is launched with -Djava.io.tmpdir=$root/.java_tmp and fails if it's gone
  mkdir -p "$root/.java_tmp"
  if grep -q 'XX:MaxPermSize' "$root/variables.mk" 2>/dev/null; then
    sed -i 's/ -XX:MaxPermSize=256M//g' "$root/variables.mk"
    ok "removed MaxPermSize from $(basename "$root")/variables.mk"
  fi
  if [ -f "$root/sims/verilator/Makefile" ] && \
     grep -q 'VERILATOR := verilator --cc --exe$' "$root/sims/verilator/Makefile"; then
    sed -i 's/VERILATOR := verilator --cc --exe$/VERILATOR := verilator --cc --exe --no-timing/' \
      "$root/sims/verilator/Makefile"
    ok "added --no-timing to $(basename "$root") Verilator flags"
  fi
  for f in "$root/sims/common-sim-flags.mk" "$root/sims/verilator/Makefile" "$root/variables.mk"; do
    if [ -f "$f" ] && grep -q 'std=c++11' "$f"; then
      sed -i 's/-std=c++11/-std=c++17/g' "$f"
      ok "bumped C++ standard to c++17 in $(basename "$root")/$(basename "$f")"
    fi
  done
}

# Copy an overlay file into a lab tree, leaving it untouched (mtime included)
# when the contents already match so make doesn't see a change.
install_overlay() {
  local src="$1" dst="$2"
  cmp -s "$src" "$dst" 2>/dev/null && return 0
  mkdir -p "$(dirname "$dst")" && cp "$src" "$dst" && ok "installed overlay $(basename "$dst")"
}

# A "variant" is a second build of an existing CONFIG with some source file
# swapped (e.g. 5-stage Sodor with bypassing off). It gets its own simulator
# name and generated-src/output directories so it never clobbers the base build:
#   simulator-<variant>-chipyard-<CONFIG>, output/chipyard.TestHarness.<CONFIG>_<variant>/
variant_args() {
  local cfg="$1" variant="${2:-}"
  [ -n "$variant" ] && printf '%s\n' "sim_prefix=simulator-$variant" "long_name=chipyard.TestHarness.${cfg}_$variant"
}
sim_path()   { local root="$1" cfg="$2" v="${3:-}"; echo "$root/sims/verilator/simulator${v:+-$v}-chipyard-$cfg"; }
output_dir() { local root="$1" cfg="$2" v="${3:-}"; echo "$root/sims/verilator/output/chipyard.TestHarness.$cfg${v:+_$v}"; }

# build_chipyard_sim <root> <CONFIG> [variant]  — returns non-zero on failure
build_chipyard_sim() {
  local root="$1" cfg="$2" variant="${3:-}"
  local sim; sim="$(sim_path "$root" "$cfg" "$variant")"
  local name="$cfg${variant:+ ($variant)}"
  if [ -x "$sim" ]; then ok "already built: $name"; return 0; fi
  local -a va; mapfile -t va < <(variant_args "$cfg" "$variant")
  log "Building $name (this takes a while)"
  # lab3's common.mk copies BOOM's *_sw.cc into generated-src/<long_name>/ and
  # races the generator under -j on a fresh config unless the dir exists
  mkdir -p "$root/sims/verilator/generated-src/chipyard.TestHarness.$cfg${variant:+_$variant}"
  ( cd "$root/sims/verilator" && make CONFIG="$cfg" "${va[@]}" -j"$JOBS" )
  if [ ! -x "$sim" ]; then
    # Verilator precompiled-header race seen on some versions; seed and retry.
    local ln="chipyard.TestHarness.$cfg${variant:+_$variant}"
    local bd="$root/sims/verilator/generated-src/$ln/$ln"
    if [ -d "$bd" ] && [ ! -f "$bd/VTestHarness__pch.h.fast" ]; then
      warn "applying PCH workaround for $name"
      printf '#include "VTestHarness__pch.h"\n' > "$bd/VTestHarness__pch.h.fast"
      printf '#include "VTestHarness__pch.h"\n' > "$bd/VTestHarness__pch.h.slow"
      # Call Verilator's generated makefile directly: re-running the top-level
      # make can regenerate the model dir and wipe the files seeded above.
      make VM_PARALLEL_BUILDS=1 -C "$bd" -f VTestHarness.mk -j"$JOBS"
    fi
  fi
  if [ -x "$sim" ]; then ok "built $name"; else warn "build failed: $name"; return 1; fi
}

# build_variant <root> <CONFIG> <variant> <file-in-tree> <replacement-file>
# Swaps the file in, builds, and restores the original byte-for-byte with its
# old mtime (so the base simulator is not considered stale afterwards).
build_variant() {
  local root="$1" cfg="$2" variant="$3" file="$4" repl="$5"
  [ -x "$(sim_path "$root" "$cfg" "$variant")" ] && { ok "already built: $cfg ($variant)"; return 0; }
  local backup; backup="$(mktemp)"
  cp -p "$file" "$backup"
  trap 'cp -p "'"$backup"'" "'"$file"'"' EXIT INT TERM
  cp "$repl" "$file"
  build_chipyard_sim "$root" "$cfg" "$variant"; local rc=$?
  cp -p "$backup" "$file"; rm -f "$backup"
  trap - EXIT INT TERM
  return $rc
}

# Print one shell command per simulation; run_jobs executes them PAR-wide.
# sim_job <root> <CONFIG> <variant|-> <make-target> <binary [args]> [extra make vars...]
sim_job() {
  local root="$1" cfg="$2" variant="$3" target="$4" binary="$5"; shift 5
  [ "$variant" = "-" ] && variant=""
  [ -x "$(sim_path "$root" "$cfg" "$variant")" ] || { warn "no simulator for $cfg${variant:+ ($variant)}; skipping $(basename "${binary%% *}")" >&2; return; }
  local out; out="$(output_dir "$root" "$cfg" "$variant")"
  local first="${binary%% *}" rest=""
  [ "$first" != "$binary" ] && rest="_$(echo "${binary#* }" | tr ' ' '_')"
  local name; name="$(basename "${first%.*}")$rest"
  local stamp="$out/$name.done"
  local va; va="$(variant_args "$cfg" "$variant" | tr '\n' ' ')"
  # -o: treat the simulator as up to date. Installing an overlay config makes
  # every Scala source look newer than existing builds, and make would otherwise
  # regenerate each simulator at run time. Delete a simulator to force a rebuild.
  local sim; sim="$(sim_path "$root" "$cfg" "$variant")"
  printf '%s\n' "mkdir -p '$out'; if [ -z \"\$FORCE\" ] && [ -f '$stamp' ]; then echo '[skip] $cfg${variant:+/$variant} $name'; exit 0; fi; rm -f '$stamp'; cd '$root/sims/verilator' && make -o '$sim' CONFIG=$cfg $va sim_out_name='$out/$name' $* $target BINARY='$binary' >'$out/$name.make.log' 2>&1 && [ \$(grep -c . '$out/$name.log' 2>/dev/null || echo 0) -ge 2 ] && touch '$stamp' && echo '[done] $cfg${variant:+/$variant} $name' || echo '[FAIL] $cfg${variant:+/$variant} $name (see $out/$name.make.log)'"
}

run_jobs() {
  local jobs; jobs="$(cat)"
  [ -n "$jobs" ] || return 0
  log "Running $(printf '%s\n' "$jobs" | wc -l) simulations, $PAR at a time"
  printf '%s\n' "$jobs" | xargs -P "$PAR" -d '\n' -I{} bash -c '{}'
}

# ----------------------------------------------------------------------------
# Test-binary toolchain
#
# The labs expect Berkeley's riscv64-unknown-elf toolchain with libgloss-htif
# (htif_nano.specs etc.). Each Chipyard lab vendors libgloss-htif as source, so
# build it against whatever bare-metal GCC is installed. The riscv-tests
# benchmarks (labs 1 & 3) use the freestanding riscv-tests env instead.
# ----------------------------------------------------------------------------
HTIF_STUBS="$REPO_ROOT/scripts/htif_stubs.c"

# build_libgloss <lab-root> — prints the install lib dir
build_libgloss() {
  local root="$1" lab; lab="$(basename "$root")"
  local prefix="$BUILD_DIR/libgloss/$lab" bdir="$BUILD_DIR/libgloss/$lab-build"
  if [ ! -f "$prefix/lib/libgloss_htif.a" ]; then
    rm -rf "$bdir" && mkdir -p "$bdir"
    ( cd "$bdir" && CFLAGS="-O2 $RV64_ARCH" "$root/toolchains/libgloss/configure" \
        --prefix="$prefix" --host=riscv64-unknown-elf --disable-multilib >/dev/null && \
      make -j"$JOBS" >/dev/null && \
      { make install >/dev/null 2>&1 || true; } ) >&2   # install's libdir sanity check fails harmlessly
    [ -f "$prefix/lib/libgloss_htif.a" ] || die "libgloss-htif build failed for $lab"
    ok "built libgloss-htif for $lab" >&2
  fi
  echo "$prefix/lib"
}

# riscv-tests `env` nested submodule (provides encoding.h)
ensure_rvtest_env() {
  local rt="$1"
  if [ ! -f "$rt/env/encoding.h" ]; then
    log "Initializing riscv-tests env submodule"
    ( cd "$rt" && git submodule update --init env ) || warn "env submodule init failed"
  fi
}

# build_rvtest_binary <out> <riscv-tests-root> <arch-flags> <extra-cflags> <include-dir> <src...>
build_rvtest_binary() {
  local out="$1" rt="$2" arch="$3" extra="$4" incdir="$5"; shift 5
  local common="$rt/benchmarks/common"
  mkdir -p "$(dirname "$out")"
  # shellcheck disable=SC2086
  riscv64-unknown-elf-gcc $arch -mcmodel=medany -static -fno-common -fno-builtin-printf \
    -nostdlib -nostartfiles $extra -I"$rt/env" -I"$common" -I"$incdir" \
    -o "$out" "$@" "$common/syscalls.c" "$common/crt.S" "$HTIF_STUBS" \
    -T "$common/test.ld" -lm -lgcc 2>&1 | grep -v -E 'RWX permissions|executable stack'
  [ -x "$out" ]
}

# ----------------------------------------------------------------------------
# Lab 1 — Sodor pipelines
#   3.x : towers on every pipeline
#   3.4/3.5/3.7 : full suite traced on the 1-stage (3.7 is an analysis of these traces)
#   3.6 : full suite on the 5-stage with full bypassing vs full interlocking
#   4.1 : branch-heavy program
# ----------------------------------------------------------------------------
lab1() {
  local ROOT="$LABS_DIR/lab1"
  [ -d "$ROOT/sims" ] || die "lab1 not initialized"
  fix_chipyard_build "$ROOT"
  local BMARKS="$ROOT/generators/riscv-sodor/riscv-bmarks"
  local CONSTS="$ROOT/generators/riscv-sodor/src/main/scala/rv32_5stage/consts.scala"
  local SUITE="dhrystone median multiply qsort rsort towers vvadd"
  local cfg b

  for cfg in Sodor1StageConfig Sodor2StageConfig Sodor3StageConfig Sodor5StageConfig SodorUCodeConfig; do
    build_chipyard_sim "$ROOT" "$cfg"
  done
  local nobypass="$BUILD_DIR/lab1/consts-nobypass.scala"
  mkdir -p "$BUILD_DIR/lab1"
  sed 's/USE_FULL_BYPASSING = true/USE_FULL_BYPASSING = false/' "$CONSTS" > "$nobypass"
  grep -q 'USE_FULL_BYPASSING = false' "$nobypass" || die "could not derive no-bypass consts.scala"
  build_variant "$ROOT" Sodor5StageConfig nobypass "$CONSTS" "$nobypass"

  log "Lab1: build Problem 4.1 branch-heavy program (rv32i, -O0)"
  local RT="$LABS_DIR/lab2/toolchains/riscv-tools/riscv-tests"   # lab2 ships the rv32-capable env
  ensure_rvtest_env "$RT"
  local BRANCHY="$BUILD_DIR/lab1/branchy.riscv"
  build_rvtest_binary "$BRANCHY" "$RT" "-march=rv32i_zicsr -mabi=ilp32" "-O0" "$OVERLAYS/lab1" \
    "$OVERLAYS/lab1/branchy.c" "$OVERLAYS/lab1/rv32_stubs.c" && ok "built branchy.riscv" || warn "branchy build failed"

  {
    for cfg in Sodor1StageConfig Sodor2StageConfig Sodor3StageConfig Sodor5StageConfig SodorUCodeConfig; do
      sim_job "$ROOT" "$cfg" - run-binary "$BMARKS/towers.riscv"
    done
    for b in $SUITE; do
      [ "$b" = towers ] && continue
      sim_job "$ROOT" Sodor1StageConfig - run-binary "$BMARKS/$b.riscv"
      sim_job "$ROOT" Sodor5StageConfig - run-binary "$BMARKS/$b.riscv"
    done
    for b in $SUITE; do
      sim_job "$ROOT" Sodor5StageConfig nobypass run-binary "$BMARKS/$b.riscv"
    done
    if [ -x "$BRANCHY" ]; then
      sim_job "$ROOT" Sodor1StageConfig - run-binary "$BRANCHY"
      sim_job "$ROOT" Sodor5StageConfig - run-binary "$BRANCHY"
    fi
  } | run_jobs
  ok "lab1 runs complete"
}

# ----------------------------------------------------------------------------
# Lab 2 — Rocket caches
#   3.3 naive transpose; 3.4 8x8 blocked; 3.5 blocked at 1/2/4/8-way (4 KiB);
#   3.6 two-level blocked on the L2 config; 4.1 ccbench sweep on the mystery config
# ----------------------------------------------------------------------------
lab2() {
  local ROOT="$LABS_DIR/lab2"
  [ -d "$ROOT/sims" ] || die "lab2 not initialized"
  fix_chipyard_build "$ROOT"
  install_overlay "$OVERLAYS/lab2/CS152ReproConfigs.scala" \
    "$ROOT/generators/chipyard/src/main/scala/config/CS152ReproConfigs.scala"
  local cfg v s
  for cfg in CS152RocketConfig CS152RocketD2WayConfig CS152RocketD4WayConfig CS152RocketD8WayConfig \
             CS152RocketL2Config CS152RocketMysteryConfig; do
    build_chipyard_sim "$ROOT" "$cfg"
  done

  local GLOSS; GLOSS="$(build_libgloss "$ROOT")"
  local TESTDIR="$ROOT/lab/directed" OUT="$BUILD_DIR/lab2"
  mkdir -p "$OUT"
  log "Lab2: build transpose variants"
  for v in naive blocked l2blocked; do
    # shellcheck disable=SC2086
    riscv64-unknown-elf-gcc $RV64_ARCH -O2 -std=gnu11 -Wall -B"$GLOSS" -L"$GLOSS" -specs=htif_nano.specs \
      -I"$TESTDIR" -o "$OUT/transpose-$v.riscv" "$OVERLAYS/lab2/transpose_$v.c" "$TESTDIR/trap.c" 2>&1 \
      | grep -v 'RWX permissions'
    [ -x "$OUT/transpose-$v.riscv" ] && ok "built transpose-$v.riscv" || warn "transpose-$v build failed"
  done

  log "Lab2: build ccbench caches micro-benchmark"
  local CC="$ROOT/lab/open1/ccbench"
  # shellcheck disable=SC2086
  riscv64-unknown-elf-gcc $RV64_ARCH -std=gnu99 -O2 -ffast-math -funroll-loops -mcmodel=medany \
    -I"$CC/common" -o "$OUT/caches" "$CC/caches/caches.c" "$CC/common/cctimer.c" \
    "$CC/common/barrier.c" "$CC/common/cclfsr.c" -static -B"$GLOSS" -L"$GLOSS" \
    -specs=htif.specs -specs=htif_argv.specs -Wl,--defsym=__heap_size=4M -lm 2>&1 | grep -v 'RWX permissions'
  [ -x "$OUT/caches" ] && ok "built caches" || warn "ccbench build failed"

  # Sizes/iterations from lab/open1/Makefile (4-byte elements, cache-line stride).
  local CCB_SIZES="262144 131072 65536 49152 32768 24576 16384 12288 8192 6144 4096 2048 1024"
  {
    sim_job "$ROOT" CS152RocketConfig      - run-binary-fast-hex "$OUT/transpose-naive.riscv"
    sim_job "$ROOT" CS152RocketConfig      - run-binary-fast-hex "$OUT/transpose-blocked.riscv"
    for cfg in CS152RocketD2WayConfig CS152RocketD4WayConfig CS152RocketD8WayConfig; do
      sim_job "$ROOT" "$cfg"               - run-binary-fast-hex "$OUT/transpose-blocked.riscv"
    done
    sim_job "$ROOT" CS152RocketL2Config    - run-binary-fast-hex "$OUT/transpose-blocked.riscv"
    sim_job "$ROOT" CS152RocketL2Config    - run-binary-fast-hex "$OUT/transpose-l2blocked.riscv"
    if [ -x "$OUT/caches" ]; then
      for s in $CCB_SIZES; do
        sim_job "$ROOT" CS152RocketMysteryConfig - run-binary-fast-hex "$OUT/caches $s 10000 0" timeout_cycles=500000000
      done
    fi
  } | run_jobs
  ok "lab2 runs complete"
}

# ----------------------------------------------------------------------------
# Lab 3 — BOOM
#   3.3 : worst case -> +64 PRF -> +16 ROB -> +branch prediction (cumulative)
#   4.1 : CS152SWPredBoomConfig with the stock bimodal vs the custom predictor
# ----------------------------------------------------------------------------
lab3() {
  local ROOT="$LABS_DIR/lab3"
  [ -d "$ROOT/sims" ] || die "lab3 not initialized"
  fix_chipyard_build "$ROOT"
  install_overlay "$OVERLAYS/lab3/CS152ReproBoomConfigs.scala" \
    "$ROOT/generators/chipyard/src/main/scala/config/CS152ReproBoomConfigs.scala"
  local SWEEP="CS152BaselineBoomConfig CS152BoomPRF64Config CS152BoomROB16Config CS152BoomBrPredConfig"
  local cfg bm
  for cfg in $SWEEP CS152SWPredBoomConfig; do build_chipyard_sim "$ROOT" "$cfg"; done
  build_variant "$ROOT" CS152SWPredBoomConfig custom \
    "$ROOT/generators/boom/src/main/resources/csrc/predictor_sw.cc" "$OVERLAYS/lab3/predictor_custom.cc"

  # chipyard's run-bmark-tests expects prebuilt binaries under $RISCV/.../share/riscv-tests
  # (Berkeley's install), so build the report's benchmarks from the submodule.
  # dhrystone is K&R C, so allow the legacy-C downgrades.
  local RT="$ROOT/toolchains/riscv-tools/riscv-tests"
  ensure_rvtest_env "$RT"
  local OUT="$BUILD_DIR/lab3"; mkdir -p "$OUT"
  local PERMISSIVE="-Wno-implicit-int -Wno-implicit-function-declaration -fpermissive"
  local BMARKS="dhrystone median multiply qsort spmv towers vvadd"
  local built=""
  log "Lab3: build riscv-tests benchmarks"
  for bm in $BMARKS; do
    local dir="$RT/benchmarks/$bm"
    # shellcheck disable=SC2086
    if build_rvtest_binary "$OUT/$bm.riscv" "$RT" "$RV64_ARCH" "-std=gnu99 -O2 -ffast-math $PERMISSIVE" "$dir" $dir/*.c >/dev/null 2>&1; then
      built="$built $bm"; ok "built $bm"
    else
      warn "build failed: $bm"
    fi
  done

  {
    for cfg in $SWEEP CS152SWPredBoomConfig; do
      for bm in $built; do sim_job "$ROOT" "$cfg" - run-binary "$OUT/$bm.riscv"; done
    done
    for bm in $built; do sim_job "$ROOT" CS152SWPredBoomConfig custom run-binary "$OUT/$bm.riscv"; done
  } | run_jobs
  ok "lab3 runs complete"
}

# ----------------------------------------------------------------------------
# Lab 4 — RISC-V vector assembly on Spike
#
# NOTE: the course's Spike had a timing model (BTB/BHT/latencies); stock Spike
# does not, so mcycle == minstret here and only instruction counts and cache
# statistics are meaningful.
# ----------------------------------------------------------------------------
lab4() {
  local ROOT="$LABS_DIR/lab4"
  local BM="$ROOT/benchmarks"
  [ -d "$BM" ] || die "lab4 benchmarks not found"
  [ -x "$RISCV/bin/spike" ] || die "spike not found under $RISCV/bin"

  if grep -q 'zvlsseg\|--varch\|--ic=64:4:64:16' "$BM/Makefile" 2>/dev/null; then
    log "Lab4: patching Makefile for the modern toolchain/Spike"
    sed -i 's/-Wa,-march=rv64gcv_zvlsseg/-march=rv64gcv_zicsr_zifencei -mabi=lp64d/g' "$BM/Makefile"
    sed -i 's/--varch=vlen:512,elen:64,dlen:128 //g; s/--br=3:28:512:6 //g' "$BM/Makefile"
    sed -i 's/--ic=64:4:64:16/--ic=64:4:64/g; s/--dc=64:4:64:16/--dc=64:4:64/g; s/--l2=1024:8:64:58/--l2=1024:8:64/g' "$BM/Makefile"
  fi
  [ -f "$BM/common/malloc_stub.c" ] || die "lab4 malloc stub missing (expected in the lab4 submodule)"

  log "Lab4: compile all benchmarks"
  ( cd "$BM" && make -k -j"$JOBS" >/dev/null 2>&1 ) || warn "some benchmarks failed to build (open-ended ones may be unimplemented)"

  # Each run's stdout (mcycle/minstret + cache stats) goes to <bench>.result,
  # with the exit status appended so analysis can flag failures.
  log "Lab4: run benchmarks on Spike"
  local b
  for b in csaxpy cmplxmult dgemv dgemm imax spmv rsort \
           vec-csaxpy vec-cmplxmult vec-dgemv vec-dgemm vec-imax vec-spmv vec-rsort; do
    [ -f "$BM/$b.riscv" ] || { warn "missing $b.riscv"; continue; }
    spike --isa=rv64gcv_zicntr --ic=64:4:64 --dc=64:4:64 --l2=1024:8:64 "$BM/$b.riscv" \
      >"$BM/$b.result" 2>&1
    local rc=$?
    echo "exit_status = $rc" >> "$BM/$b.result"
    [ $rc -eq 0 ] && ok "$b" || warn "$b exited with $rc"
  done
  ok "lab4 runs complete"
}

# ----------------------------------------------------------------------------
# Lab 5 — cache coherence on dual-core Rocket
#   3.3–3.5 : mt-vvadd naive/opt on MSI and MI;  4 : mt-matmul naive/opt
# (MESI is run too for comparison.)
# ----------------------------------------------------------------------------
lab5() {
  local ROOT="$LABS_DIR/lab5"
  [ -d "$ROOT/sims" ] || die "lab5 not initialized"
  fix_chipyard_build "$ROOT"
  local CONFIGS="Lab5MSIDualRocketConfig Lab5MIDualRocketConfig Lab5MESIDualRocketConfig"
  local cfg b
  for cfg in $CONFIGS; do build_chipyard_sim "$ROOT" "$cfg"; done

  local GLOSS; GLOSS="$(build_libgloss "$ROOT")"
  local L="$ROOT/lab" OUT="$BUILD_DIR/lab5"; mkdir -p "$OUT"
  local TESTS="mt-vvadd-naive mt-vvadd-opt mt-matmul-naive mt-matmul-opt"
  log "Lab5: build multithreaded benchmarks"
  for b in $TESTS; do
    # Same flags as lab/Makefile, but with the TLS-free util.c (see overlay header).
    # shellcheck disable=SC2086
    riscv64-unknown-elf-gcc $RV64_ARCH -O2 -Wall -Wno-unused-function -pedantic -std=c11 \
      -I "$L/common" -B"$GLOSS" -L"$GLOSS" -specs=htif_nano.specs -o "$OUT/$b.riscv" \
      "$L/$b"/*.c "$OVERLAYS/lab5/util.c" -Wl,--defsym=__main=main -T "$L/common/data.ld" 2>&1 \
      | grep -v 'RWX permissions'
    [ -x "$OUT/$b.riscv" ] && ok "built $b.riscv" || warn "$b build failed"
  done

  {
    for cfg in $CONFIGS; do
      for b in $TESTS; do
        [ -x "$OUT/$b.riscv" ] && sim_job "$ROOT" "$cfg" - run-binary-fast "$OUT/$b.riscv"
      done
    done
  } | run_jobs
  ok "lab5 runs complete"
}

# ----------------------------------------------------------------------------
# Analysis
# ----------------------------------------------------------------------------
analyze() {
  command -v python3 >/dev/null 2>&1 || { warn "python3 not found; skipping analysis"; return; }
  log "Analyze: ${*:-all labs}"
  python3 "$REPO_ROOT/scripts/analyze.py" "$@" || warn "analysis reported problems"
}

# ----------------------------------------------------------------------------
# Dispatch
# ----------------------------------------------------------------------------
main() {
  local target="${1:-all}"
  case "$target" in
    analyze|plots) shift; analyze "$@"; return ;;   # needs only python3 + matplotlib
    check)         check; return ;;
  esac
  setup_env
  log "RISCV=$RISCV  JAVA_HOME=${JAVA_HOME:-<none>}  JOBS=$JOBS  PAR=$PAR"
  case "$target" in
    lab1|lab2|lab3|lab4|lab5) "$target"; analyze "$target" ;;
    all) lab4; lab1; lab2; lab3; lab5; analyze ;;
    *)   die "unknown target '$target' (use: lab1..lab5|all|analyze|check)" ;;
  esac
  log "Done: $target"
}

main "$@"

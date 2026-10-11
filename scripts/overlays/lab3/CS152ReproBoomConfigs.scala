package chipyard

import freechips.rocketchip.config.{Config}
import freechips.rocketchip.subsystem.{TilesLocated, InSubsystem}

// Installed by run_labs.sh (scripts/overlays/lab3) — not part of the original lab.
//
// Problem 3.3 walks the 1-wide CS152 baseline BOOM from the worst case
// (33 PRF / 4 ROB / no branch prediction) toward the improved design, one
// change at a time and keeping earlier changes. Rather than hand-editing
// WithNCS152BaselineBooms between builds, each design point is its own config.

class WithCS152BoomKnobs(prf: Int, rob: Int, bpd: Boolean) extends Config((site, here, up) => {
  case TilesLocated(InSubsystem) => up(TilesLocated(InSubsystem), site) map {
    case tp: boom.common.BoomTileAttachParams => tp.copy(tileParams = tp.tileParams.copy(
      core = tp.tileParams.core.copy(
        numIntPhysRegisters = prf,
        numRobEntries = rob,
        enableBranchPrediction = bpd)))
    case other => other
  }
})

// Worst case is CS152BaselineBoomConfig itself.

class CS152BoomPRF64Config extends Config(
  new WithCS152BoomKnobs(prf = 64, rob = 4, bpd = false) ++
  new CS152BaselineBoomConfig)

class CS152BoomROB16Config extends Config(
  new WithCS152BoomKnobs(prf = 64, rob = 16, bpd = false) ++
  new CS152BaselineBoomConfig)

class CS152BoomBrPredConfig extends Config(
  new WithCS152BoomKnobs(prf = 64, rob = 16, bpd = true) ++
  new CS152BaselineBoomConfig)

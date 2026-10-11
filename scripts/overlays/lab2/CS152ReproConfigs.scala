package chipyard

import freechips.rocketchip.config.{Config}
import freechips.rocketchip.subsystem._

// Installed by run_labs.sh (scripts/overlays/lab2) — not part of the original lab.
//
// Problem 3.5: sweep L1 D$ associativity while holding capacity at 4 KiB
// (sets x ways x 64 B), as the handout asks, without editing CS152RocketConfig.

class CS152RocketD2WayConfig extends Config(
  new WithL1DCacheSets(32) ++
  new WithL1DCacheWays(2) ++
  new CS152RocketConfig)

class CS152RocketD4WayConfig extends Config(
  new WithL1DCacheSets(16) ++
  new WithL1DCacheWays(4) ++
  new CS152RocketConfig)

class CS152RocketD8WayConfig extends Config(
  new WithL1DCacheSets(8) ++
  new WithL1DCacheWays(8) ++
  new CS152RocketConfig)

# Simulator change notice — 2026-09-25

This is a modified version of BioSim based on the public upstream `main` revision
`9a45d55b`. The upstream history, GNU GPL version 3 license, NASA Johnson Space
Center project attribution, and embedded author/copyright/third-party notices
are retained. The changes below concern the Java simulator, its schema,
regression fixtures, documentation, and standalone build packaging.

## Behavior changes

- EVA departure and return now attach the person to the destination roster.
  Transfers are queued while crew groups tick and committed together after all
  simulation modules, before sensors and tick listeners. This prevents missing
  membership and double ticking caused by group iteration order.
- `BioDriver.advanceTicks(n)` and `POST /api/simulation/{id}/tick?n=N` support
  batched paused stepping. The endpoint rejects malformed/nonpositive counts and
  returns both `ticks` and `advanced`. A batch stops at a configured end condition.
  Automatic ticks, pause/end, reset/restart, and manual batches now share the
  driver monitor. Woken or replaced workers recheck ownership before ticking;
  stopping a paused worker cannot add a post-end tick. Repeated terminal batches
  return zero progress until reset/restart. Unstarted/reset fixtures still support
  manual stepping, and automatic end-condition looping remains supported. Explicit
  stop (including from a tick callback) does not restart a loop. Existing callback
  numbering is unchanged.
- Fan flow uses the local ideal-gas density and volumetric flow. Air consumers,
  resource movers, and dehumidifiers account for hours per tick; mass-port rate
  caps are expressed per hour rather than per tick in these paths.
- Air transfer filters the requested total once before taking the component
  gases; it does not independently perturb each gas again when returning air.
  The new relative Gaussian filter has zero output for a zero command and is
  disabled unless explicitly enabled. Store withdrawals are bounded by available
  inventory, including stochastic requests and pipe-capacity accounting.
- Crew water outputs sum to consumed potable water. Waste and exhaled CO2 depend
  on actual food and O2 consumption rather than unmet demand.
- Optional XML selectors enable Langmuir CO2 beds, Faraday electrolysis,
  stoichiometric Sabatier conversion, damper-commanded fans, one-node cabin
  thermal response, volume-equipped gas tanks, and PCA injection control.
  `LINEAR` equipment and frozen cabin temperature remain the defaults. See the
  [configuration manual](users_manual.md#opt-in-physical-laws) for control units.
- The frozen-temperature dehumidifier threshold changes from 0.52 to 0.02 water
  mole fraction. This and the fan/timestep/crew fixes change some existing
  configurations even when no new optional selectors are enabled.

## Standalone regression coverage

Run `mvn -B clean verify` with JDK 21 from the repository root. Instructions for
starting the Java server and building the container are in the
[README](../README.md#building-and-testing-standalone).

- `CrewTransferAtomicityIT` uses `configuration/test/CrewTransferInit.xml` with
  four synthetic crew members, disabled mortality, and zero airlock volume to
  isolate roster transitions. Six simulations run 7,200 ticks each, explicitly
  covering both crew-group iteration orders. Every tick checks unique membership,
  the person's current-group reference, and exactly one activity-clock advance;
  repeated EVA departures and returns are required for the test to pass.
- `ClosedLoopMassIT` uses `configuration/test/ClosedLoopMassInit.xml`, a closed
  air/water/reaction circuit without crew, leaks, resupply, or overflow. It runs
  1,440 one-minute ticks, accounts for gas species with their own molar masses,
  includes CO2 in the adsorption bed, and rejects non-finite/negative inventory.
  Per-tick residual is bounded by 0.0001 kg and cumulative drift by 0.01 kg,
  including single-precision accumulation. Nonzero electrolysis, adsorption,
  desorption/reaction, and condensation are required.
- `BioDriverLifecycleTest` coordinates actual workers with barriers and observed
  wait states: stop while paused/throttled, batch termination, repeated terminal
  steps, reset/restart, in-flight pause/end serialization, callbacks, and looping.
  `SimulationLifecycleIT` uses a temporary loopback HTTP server to check exact
  batch acknowledgements against terminal snapshots, including concurrent requests.
- The existing humans/crops mass ledger and its deliberately incomplete-ledger
  negative control remain enabled, alongside the closed gas-transfer test.
  Unit/integration tests also cover physical-law equations, zero-input cases,
  filter behavior, and XML default versus opt-in implementation dispatch.

All fixtures are included. Missing files fail the tests; there are no external
fixture overrides or conditional skips. These fixtures are regression cases,
not calibrated mission configurations.

## Limits

These are approximate, lumped simulation laws, not flight-qualified equipment or
validated physiological models. Passing these tests does not prove arbitrary
plant configurations conserve mass, reproduce a mission, or remain habitable.
Leaks, airlock dumps, untracked compartments, discarded store overflow, and
unsupported subsystem combinations require explicit accounting. The crew
regression intentionally disables mortality to test transfer invariants, not
survival. Timestep fixes do not establish convergence of every legacy subsystem.
Stochastic runs are not guaranteed to be bit-for-bit reproducible.

Transfer atomicity here means a consistent roster at completed tick boundaries;
it does not claim transaction isolation for concurrent arbitrary API mutations.
Use paused stepping with one controlling client. The API is unauthenticated and
should not be exposed directly to untrusted networks.

The container build runs the same Maven suite and retains runtime dependencies
as separate JARs so their license/notice resources remain intact. Both simulator
JAR forms additionally preserve those embedded resources under per-artifact
`META-INF/dependency-notices/` paths and BioSim's GPL text under
`META-INF/biosim/LICENSE`, avoiding merged-resource collisions. Distributing a
binary or container does not remove the GPL's applicable source-distribution
obligations. BioSim remains GPL-3.0; third-party dependencies keep their own terms.

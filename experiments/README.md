# BioSim attacker simulation

CLI-backed prompt-injection experiments against a simulated life-support plant. The original episode driver owns simulator time; the operator CLI retains its session between watches. The default executable is a deterministic fake CLI, not an LLM. Live inference requires explicit opt-in and user-supplied credentials and CLI installation.

Start with **[DEPLOY.md](DEPLOY.md)** for fresh setup, tests and container qualification, then **[MODELS.md](MODELS.md)** to add an API-compatible model with private credentials and a bounded smoke run. This directory is the experiment runtime inside the unified checkout; GPL BioSim source is in sibling `../simulator` and inputs stay under `experiments/`.

## Included

- Original console/state/scoring and CLI watch loop, assembled identity prompts, persistent sessions, delayed attack frames and cached repeat reads.
- All 13 identity pack directories, all six plant configurations, frozen attack/benign inputs and protocol snapshots.
- Separate life/S-band duty experiments, shared dual-prompt experiments, three-arm comparisons, T0/T1/T2/unlabeled variants, 16-turn and 32-turn recovered-watch protocols, and controls.
- Versioned manifests, a portable launcher, streamed Chat Completions/Responses relay, shared pacing, container seating, and offline qualification.
- Complete available historical launch/adapter/adaptive-writer code, gated and inventoried under `historical/`; earlier cohorts are not replaced by newer protocols.
- Tests and explicit dependency/configuration examples. Publication and release tooling have their own subdirectories.

## Quickstart

On Linux with Python >=3.11, Java 21 and Maven, use the unified checkout containing `simulator/` and `experiments/`. From the unified root:

```sh
(cd simulator && mvn clean verify)
cd experiments
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[dev]'
test -f ../simulator/target/biosim-2.0.0-jar-with-dependencies.jar
.venv/bin/python scripts/run_experiment.py --validate
.venv/bin/python scripts/run_experiment.py --output /tmp/eclss-control
```

The default host JAR resolves to `../simulator/target/biosim-2.0.0-jar-with-dependencies.jar`; set `BIOSIM_JAR` only to override it explicitly.

No virtualenv activation is needed; the host fake uses the invoking Python environment. Clear inherited `BIOSIM_JAR`, `BIOSIM_URL`, `BIOSIM_PORT`, `BIOSIM_RUNS_ROOT` and `BIOSIM_PLANT_IMAGE` before a fresh test to avoid targeting an unrelated plant or output tree. Docker and a real operator CLI are not required for this host-only check. This starts one fresh JVM and the fake CLI, executes 24 hours of warmup plus 24 four-hour watches, and writes the result outside the checkout. No provider configuration or model credential is required. Output directories must not already exist. Fake runs are explicitly marked offline and are not scientific model observations.

## Scientific boundaries

See [PROTOCOLS.md](PROTOCOLS.md) for definitions and fidelity constraints and [OUTPUTS.md](OUTPUTS.md) for records. The physical simulator has enabled stochastic filters: equal uplink seeds do not imply equal plant trajectories. Sanitized identities are not byte-identical to historical private prompts. Neither fake qualification nor a different provider/CLI version proves identical historical inference.

The supported experimental operator is Grok CLI with the original system-prompt override/MCP/session contract. Legacy Cursor/Hermes seating and adaptive-writer treatments retain their original available code in [historical/](historical/README.md), inert by default. They require separately reviewed configuration; frozen attack text is not an adaptive-writer substitute. No proprietary executable, authentication file, private service configuration, or historical run archive is distributed.

Original code is MIT; original documentation and prompt contributions are CC BY 4.0. Inherited simulator/configuration and other third-party rights are excluded from those grants: see [LICENSES.md](LICENSES.md).

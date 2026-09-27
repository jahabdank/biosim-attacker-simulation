# Deploy and check the conference artifact

This one repository contains the simulator, experiment runtime and cleaned results. Use a fresh working directory on Linux. The steps below make no model calls and do not require private credentials. Follow [`experiments/DEPLOY.md`](experiments/DEPLOY.md) for the full qualification, Docker isolation, troubleshooting and authorized live-operation boundaries; follow [`experiments/MODELS.md`](experiments/MODELS.md) to add an API-compatible model.

## Prerequisites and clean build

Install Java 21, Maven 3.8.7+, Python 3.11+ with `venv`, and optionally Docker Engine and Compose v2 for container qualification. If the host has several JDKs, set `JAVA_HOME` for Java 21 and verify `mvn -version` reports Java 21. Docker permissions must already be granted by the machine owner; do not change system permissions merely to run a test.

From this repository root:

```sh
(cd simulator && mvn clean verify)
cd experiments
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[dev]'
export BIOSIM_JAR="$(realpath ../simulator/target/biosim-2.0.0-jar-with-dependencies.jar)"
unset BIOSIM_URL BIOSIM_PORT BIOSIM_RUNS_ROOT
.venv/bin/python -c 'import biosim_operator, mcp; print(biosim_operator.__file__)'
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q -p no:cacheprovider
.venv/bin/python scripts/run_experiment.py --validate
```

The Java suite exercises mass conservation and atomic crew transfer using simulator-only fixtures. The Python suite uses the simulator JAR from this checkout; any skipped tests must be read before treating it as qualified. Keep output and private provider settings outside the repository. Activation of the virtual environment is optional: invoke `.venv/bin/python` consistently.

## One offline control

From `experiments/`, with `BIOSIM_JAR` still set and a fresh output path:

```sh
.venv/bin/python scripts/run_experiment.py --output /absolute/private/empty-control-directory
```

Expect a completed 24-watch technical control, four crew, zero deaths and `offline: true`. Inspect `status.json`, `attempts.jsonl`, and the episode `outcome.json`; an exit code or directory alone is not scientific completion. This fake-operator run consumes no experimental-model tokens. Do not use a control output path that already exists.

## Container qualification

From `experiments/`:

```sh
docker compose build plant
.venv/bin/python scripts/build_operator_image.py
export BIOSIM_PLANT_IMAGE=biosim-experiment-plant:local
.venv/bin/python scripts/qualify.py --container --output /absolute/private/empty-qualification-directory
```

The plant build context resolves to this repository's `simulator/`. The operator image bundles only bridges; live operators supply a legally installed CLI and their own credentials. Stop on a failed isolation check.

## Verify the released traces

From `experiments/`, use a fresh output path with at least 3 GiB free:

```sh
.venv/bin/python -m scripts.publication.archive verify --root ../results --extract-to /absolute/private/new-extraction-directory
.venv/bin/python -m scripts.publication.verify --output /absolute/private/new-extraction-directory/results
```

The first check validates ZIP checksums, inventory and every extracted file against the source manifest, then runs the episode/reference verifier before making `new-extraction-directory/results/` visible. The second command repeats that public check and can be omitted after a successful extraction. Archive checks never call a model. Keep extracted data outside the checkout; verification can take minutes on slow disks. `results/README.md` describes the archive layout and public limitations. Private source-level fidelity verification requires custodial provenance that is deliberately outside this repository.

## Authorized model experiments

Read [`experiments/MODELS.md`](experiments/MODELS.md) for the worked provider/manifest example. Keep API endpoints, deployment IDs, keys and subscription authentication files outside this repository. Verify the provider limits and route match the new manifest, run the offline smoke, then obtain permission for any live calls and provider-side spending limit. A two-watch live smoke is a separate authorized test; the offline control does not establish live-provider compatibility.

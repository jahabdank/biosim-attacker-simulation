# Deployment agent instructions

## Boundaries

Operate only in these cloned repositories and explicitly chosen scratch/output directories. Do not read ambient authentication, change global service configuration, overwrite an existing run, publish traces, or start live model inference without authorization. Default commands below use the fake CLI and make no model calls. Package/image downloads are ordinary build dependencies, not inference.

Required: Linux, Python >=3.11, Java 21 and Maven for host-JVM builds; Docker Engine with isolated bridge gateway support and Compose v2 for container operation. Docker permission must already be granted by the machine owner. Do not automatically alter group membership, sudo policy or daemon configuration. No GPU is required by the simulator.

## 1. Prepare sibling checkouts and dependencies

Expected layout:

```
workspace/
  biosim/
  biosim-attacker-simulation/
```

Clone both release repositories into this layout using their supplied repository URLs; no private runtime/archive checkout is required. From `biosim-attacker-simulation`:

```sh
python3 --version                 # >= 3.11; choose that interpreter below
java -version                    # select Java 21 if this prints another version
mvn -version                     # must also report Java 21
(cd ../biosim && mvn clean verify)
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[dev]'
export BIOSIM_JAR="$(realpath ../biosim/target/biosim-2.0.0-jar-with-dependencies.jar)"
test -f "$BIOSIM_JAR"
.venv/bin/python -c 'import sys, biosim_operator, mcp; print(sys.executable); print(biosim_operator.__file__)'
```

The clean Java build replaces stale products; crew-transfer and mass-conservation tests must run with real fixtures rather than silently skip. If the default Java is newer, select an installed Java 21 before the build (for example, `export JAVA_HOME=/path/to/jdk-21; export PATH="$JAVA_HOME/bin:$PATH"`) and confirm `mvn -version` uses it. Maven 3.8.7+ and Java 21 are prerequisites; if either is missing, ask the machine owner to install it or unpack an approved distribution in a private workspace. If `venv` is missing, request installation; do not modify system Python. Activation is optional: invoke `.venv/bin/python` consistently. The host fake CLI uses that same interpreter, while container executables use the image's runtime.

The experiment runtime uses `mcp` (major version 1). The publication tools use PyYAML (major version 6); the development extra includes PyYAML and pytest. Resolve and record exact dependency versions and image digests for a released deployment. Do not rely on an editable installation from another checkout: verify `biosim_operator.__file__` points into this checkout. Base image tags alone are not immutable pins.

## 2. Validate inputs and qualify offline

For a clean-room rehearsal, copy only the release sources into the sibling layout under a disposable directory, then repeat section 1 there (do not copy an existing `.venv`). Otherwise use the environment just created. Set `BIOSIM_JAR` to the freshly built sibling JAR and remove inherited `BIOSIM_URL`, `BIOSIM_PORT` and `BIOSIM_RUNS_ROOT` from the test environment; those variables can redirect an episode into an unrelated plant or output tree. From that experiment checkout:

```sh
unset BIOSIM_URL BIOSIM_PORT BIOSIM_RUNS_ROOT
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q -p no:cacheprovider
.venv/bin/python scripts/run_experiment.py --validate
.venv/bin/python scripts/qualify.py --output /tmp/eclss-qualification
```

`qualify.py` uses the fake CLI through the original episode loop, not a replacement chat adapter. It checks full 120-hour operation, delayed attack/cache behavior, persistent history, cap recovery and hard-error stopping. All output paths must be fresh. Confirm 24 watches, four crew and no deaths in the technical control; check `offline: true`. Live-JVM tests can skip when no JAR is configured, so a green unit-only run is not deployment qualification.

To validate all shipped manifests:

```sh
for f in manifests/*.json; do .venv/bin/python scripts/run_experiment.py --manifest "$f" --validate || exit; done
```

## 3. Container qualification

Build the sibling plant and the bridge-only operator image:

```sh
docker compose build plant
.venv/bin/python scripts/build_operator_image.py
export BIOSIM_PLANT_IMAGE=biosim-experiment-plant:local
.venv/bin/python scripts/qualify.py --container --output /tmp/eclss-container-qualification
```

Compose's build context is explicitly `../biosim`, overridable with `BIOSIM_BUILD_CONTEXT`; alternatively supply your own `BIOSIM_PLANT_IMAGE`. The controller launches a fresh plant per episode; `docker compose up` is not the experiment launcher. It creates short-lived operator/broker networks and containers and deletes only the resources it owns.

The operator is nonroot, read-only, capability-dropped and no-new-privileges, with only station documents, private scratch and the explicitly selected executable mounted. The image contains no proprietary CLI or authentication. Offline qualification mounts the supplied fake CLI. Native/API operator containers do not receive the repository, attack banks, provider configuration, host home, Docker socket or a direct plant URL. The trusted host controller requires Docker access; the operator does not.

If isolation fails, stop. Do not weaken the flags or fall back to host live inference. Some Docker installations reject the required isolation flags; report that deployment blocked.

## 4. Configure live transport explicitly

For a worked API-model addition, follow [MODELS.md](MODELS.md): private provider/credential files, matching control and smoke manifests, local validation, and separately authorized bounded inference. Existing public manifests are not edited. `--validate` checks manifest inputs only; it does **not** validate provider settings, credentials or endpoint compatibility.

Obtain a legally installed compatible Grok CLI yourself. Set `GROK_BIN` to its executable; record its version and SHA-256. It must support the flags used in `grok_harness.grok_cmd`, MCP tools, explicit session IDs/resume, and the selected model/backend. This repository does not download, ship or license it.

A network-disabled container check with Grok CLI `1.0.41` verified executable startup and parsing of the generated command-line arguments in help mode. Model inference and live-provider behavior require separate qualification.

Copy `config/providers.example.toml` to a private location **outside** the checkout. Set `BIOSIM_PROVIDERS` to that file. Supply only the models to be run. Each API entry requires its actual URL, deployment string, backend, context/output limits and a credential file; optional header/prefix settings accommodate non-Bearer services. A deliberately unauthenticated local service must opt in explicitly. No private gateway/proxy is assumed. Endpoint-specific compatibility must be checked against local stubs and your authorized service.

For subscription mode, supply `auth_file` explicitly. No home-directory authentication is discovered. The real CLI can read the episode-local copy; do not claim it is hidden from that process. The copy is removed during owned cleanup. API credentials stay in the trusted relay.

Preserve public model labels/settings and neutral cohort distinctions. Match provider context/output/backend to the selected manifest; the launcher rejects mismatches. Shared pacing and lock directories default under `/tmp`; on a dedicated machine set `BIOSIM_PACING_DIR` and `BIOSIM_LOCK_DIR` to private persistent directories if pacing must survive process restarts.

## 5. Authorized experiment

First run the relevant full-horizon control, inspect its `outcome.json`, tool delivery, roster, compaction and failure fields, and obtain authorization for the selected matrix. Then, for example:

```sh
.venv/bin/python scripts/run_experiment.py --manifest manifests/grok47-v2-t1.json --allow-live --output /absolute/private/results/new-study
```

Without `--allow-live`, this exact command runs offline with the fake CLI. `--limit` creates an explicitly labeled qualification subset, not a complete scientific matrix. Live mode always uses containers. No replacement attempts, provider substitutions or extra phases are silently launched. Historical host-only harnesses and uncontained dynamic attack writers are not supported deployment modes.

## 6. Outputs, interruption and troubleshooting

Consult `OUTPUTS.md`. Scientific completion comes from episode outcomes, not controller exit, file count or HTTP success. Keep incomplete/unexposed/invalid attempts separate from refusal or resistance. Preserve partial-death and recovered-cap records.

On interruption, allow the controller to stop its owned operator/relay/JVM resources. Inspect unresolved attempt records before any rerun. Never use broad container/process kill patterns. Do not reuse output directories; replacement lineage belongs in an explicit new manifest and study record.

Common failures: for missing `mcp`, check `.venv/bin/python -c 'import sys, mcp; print(sys.executable)'` and reinstall this checkout's dependencies with that interpreter; activation is not required. A missing JAR means the sibling simulator was not built/configured; absent Docker permission is an administrative prerequisite; missing CLI flags or backend compatibility is a third-party version limitation. A `route_error`/timeout is technical incompletion, never an attack verdict. No live provider compatibility is implied by mock qualification.

Run directories contain private operational data. Use the publication/release workflow before sharing, and independently audit licenses/privacy. No commit or upload is part of deployment.


## Historical code and release-regression checks

See `historical/README.md` and its source inventory for the preserved earlier cohorts, adaptive-writer treatments and legacy adapters. They are inert by default; do not enable archival side effects merely to inspect definitions. Earlier 16-turn and routed-200k Grok manifests are separate selectable cohorts, not aliases of v2/native runs.

For the additional real-container regression tests, explicitly set `BIOSIM_TEST_CONTAINERS=1` while running pytest in a clean copy. These tests use only synthetic executables, verify writable private `/tmp`, and prove native-shaped and offline daemon execs have stopped before timeout evidence is returned. No user authentication or inference is involved. Standard `qualify.py --container` also checks writable temporary storage on every fake watch. Preserve quiescence and exact batch-tick acknowledgement requirements; do not restore implicit tick retries for older endpoints.

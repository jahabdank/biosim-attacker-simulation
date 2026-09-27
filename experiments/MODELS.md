# Add an API-compatible model

Complete [DEPLOY.md](DEPLOY.md) first, including offline container qualification before any live run. Run commands from `experiments/` in the unified checkout with its `.venv/bin/python`; the simulator is the sibling `../simulator`, not a separate clone. A new public model label needs a private provider entry and matching manifests, not a code registry change. Do not rename an existing historical cohort to stand for a different model.

Supported transports are OpenAI-compatible **Chat Completions** and **Responses**, including streaming and tool calls through the Grok CLI. An unrelated native API is not supported merely by changing its URL; it needs a separately tested adapter. Local stubs test the relay, not a particular provider's compatibility.

## 1. Supply private configuration

Choose a nonidentifying public label (`example-api` below). Keep the actual deployment ID, endpoint and key outside every checkout. For disposable setup:

```sh
umask 077
export PRIVATE="$(mktemp -d /tmp/eclss-model.XXXXXX)"
export BIOSIM_PROVIDERS="$PRIVATE/providers.toml"
.venv/bin/python -c 'import getpass, os; from pathlib import Path; Path(os.environ["PRIVATE"], "provider-key").write_text(getpass.getpass("API key (hidden): ") + "\n")'
```

Only enter a credential you are authorized to use; the hidden prompt avoids command history. Store durable credentials in an owner-only directory instead if needed. Do not paste keys into manifests, shell commands, logs or this repository.

Create `$BIOSIM_PROVIDERS` in your editor using the following entry. Replace the URL, deployment ID and credential path with actual values; the numeric limits are **examples**, not claims about your model. TOML does not expand `$PRIVATE` or other shell variables in these fields, so use the absolute credential path printed by `printf '%s/provider-key\n' "$PRIVATE"`.

```toml
[models."example-api"]
kind = "api"
label = "Example API model"
model = "replace-with-provider-deployment-id"
api_backend = "chat_completions"
base_url = "https://provider.example.invalid/v1"
credential_file = "/absolute/private/directory/provider-key"
context_window = 131072
max_completion_tokens = 1024
pacing_group = "example-api"
```

Use `api_backend = "responses"` for Responses. `base_url` is the API prefix, **without** `/chat/completions` or `/responses`; the relay appends that endpoint. Use HTTPS for remote credentials. Default authentication is `Authorization: Bearer <key>`; services needing another scheme can set `auth_header = "api-key"` and `auth_prefix = ""`. For Chat Completions services requiring that token field, set `completion_token_field = "max_completion_tokens"`. Explicit `allow_unauthenticated = true` is only for intentionally unauthenticated local services, not a workaround for missing credentials.

Set both files to mode 600. Set `GROK_BIN` to your legally installed compatible executable as described in DEPLOY; record its version and SHA-256. API keys remain in the trusted host relay and are not mounted into the operator container. No ambient home-directory credentials are discovered.

## 2. Derive matching control and smoke manifests

This creates new files outside the checkout, leaving shipped manifests untouched. It copies the full-horizon control, sets the new model's transport limits, then derives a deliberately short technical smoke. Adjust the example 1-second request spacing to your provider's quota before generating; labels sharing a quota should share a `pacing_group`.

```sh
.venv/bin/python - <<'PY'
import copy, json, os
from pathlib import Path
from biosim_operator.provider_config import load_provider

private = Path(os.environ["PRIVATE"])
label = "example-api"
p = load_provider(label)
assert p["kind"] == "api"
control = json.loads(Path("manifests/offline-control.json").read_text())
control.update(study_id=label + "-control", purpose="New-model full-horizon control",
               model_concurrency=1, per_model_concurrency=1)
job = control["jobs"][0]
job.update(study_id=control["study_id"], job_id=label + ":control:r01", model=label,
           route=p["kind"], api_backend=p["api_backend"],
           context_window=p["context_window"], max_completion_tokens=p["max_completion_tokens"],
           reasoning_effort="provider-default", minimum_spacing_s=1.0, transient_tries=1)
smoke = copy.deepcopy(control)
smoke.update(study_id=label + "-smoke", purpose="Technical smoke only; not a scientific episode")
smoke["jobs"][0].update(study_id=smoke["study_id"], job_id=label + ":smoke:r01",
                        warmup_hours=0, turns=2, timeout=120, max_tool_turns=4,
                        recover_max_turn_watch=False, protocol_version="technical-smoke")
for name, manifest in (("control", control), ("smoke", smoke)):
    with (private / (name + ".json")).open("x") as stream:
        json.dump(manifest, stream, indent=2)
        stream.write("\n")
PY
```

The provider table key and each job's `model` must match exactly. The upstream `model` string is private routing configuration, not that public label. `route`, `api_backend`, `context_window` and `max_completion_tokens` must match the provider entry; live launch rejects mismatches. Choose a supported explicit `reasoning_effort` when needed, or retain `provider-default` (no CLI effort flag); record that choice. Keep scientific controls/treatments on matching limits, reasoning, pacing, retry and protocol settings. For attack manifests, preserve trust, identity, script hashes, exposure delay, seed and watch horizon; do not substitute this shortened smoke for a cohort.

## 3. Validate without inference

```sh
.venv/bin/python scripts/run_experiment.py --manifest "$PRIVATE/control.json" --validate
.venv/bin/python scripts/run_experiment.py --manifest "$PRIVATE/smoke.json" --validate
.venv/bin/python - <<'PY'
import os
from pathlib import Path
from biosim_operator.manifest import load_manifest
from biosim_operator.provider_config import credential, load_provider

for name in ("control", "smoke"):
    data = load_manifest(Path(os.environ["PRIVATE"]) / (name + ".json"))
    for job in data["jobs"]:
        p = load_provider(job["model"])
        assert job["route"] == p["kind"] == "api"
        for field in ("api_backend", "context_window", "max_completion_tokens"):
            assert job[field] == p[field], field
        assert credential(p)
print("Provider settings and credential files are locally valid; no endpoint contacted.")
PY
.venv/bin/python -m pytest -q tests/test_provider_transport.py tests/test_launch_boundaries.py
.venv/bin/python scripts/run_experiment.py --manifest "$PRIVATE/smoke.json" --limit 1 --output "$PRIVATE/offline-smoke"
```

`--validate` alone checks manifest structure/inputs, not providers or keys. The explicit Python check reads only the selected private files and never prints their contents or authenticates to a service. The last command uses the fake CLI regardless of provider configuration. Inspect `status.json`, `0001/episode/outcome.json` and both watch records; expect completion and `offline: true`. Outputs must be new directories.

## 4. Separately authorized bounded live smoke

**The following command makes real, potentially billable model calls. Do not run it without authorization.** Complete the container qualification and obtain permission for the configured endpoint/model and budget first.

```sh
.venv/bin/python scripts/run_experiment.py --manifest "$PRIVATE/smoke.json" --allow-live --limit 1 --output "$PRIVATE/live-smoke"
```

Bounds here are one job, two watches, four tool turns per watch, 120 seconds per watch, one relay attempt and the configured per-completion token limit. `--limit 1` alone limits jobs, not watch length or cost; CLI-internal behavior and setup time mean these are not a hard billing or whole-process wall-clock cap. Set an authorized provider-side spending limit too. Live mode always uses containers; do not bypass isolation to make a failed smoke pass.

Inspect outcome incompletion/error fields, MCP tool delivery, persistent session resume, compaction and route diagnostics/usage. A tool-cap, route error or timeout is technical incompletion, not resistance. A successful smoke still does not qualify the full horizon: separately authorize and run `control.json` with a fresh output directory before proposing a scientific matrix. Keep outputs private and record manifest, dependency/CLI/image versions and any provider identity evidence; neither a fake run nor HTTP success proves live-model equivalence.

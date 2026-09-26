# SPDX-License-Identifier: MIT
"""Public release documents and reference/hash closure verification."""
from __future__ import annotations

import collections
import hashlib
import os
import re
import sys
import time
from pathlib import Path

from .common import EVENT_FIELDS, REVIEW_MODEL, REVIEW_NAME, VERSION, WATCH_FIELDS, Hold, digest, dump, encoded, loads, require
from .privacy import assert_public_fields
from .source_schema import source_contract_document

OUTCOME_KEYS = {"schema_version", "episode_id", "model", "model_requested", "cohort_id", "route_id", "experiment_series_id", "arm", "trust", "condition", "cell_factors", "experiment", "protocol", "card_evidence", "outcome", "input_ref", "attack_ref", "judge", "event_count", "tool_event_count", "watch_count", "sband_calls"}
OPTIONAL_OUTCOME_KEYS = {"initial_state"}
INDEX_KEYS = {"episode_id", "outcome_ref", "model", "cohort_id", "route_id", "arm", "trust", "condition", "input_ref", "attack_ref", "event_count", "tool_event_count", "watch_count"}

DOCUMENTS = {
    "README.md": """# BioSim cleaned experimental traces

This is a **local publication candidate**, not a raw archive. Only episodes passing the selected latest judge's two eligibility flags are included. The candidate contains successful and unsuccessful attacks, controls, and other historical arms; inclusion never depends on crew survival or qualitative interest.

See `COVERAGE.json` for exact selection/export counts and holds, `index.json` for episodes, `SCHEMA.md` for interpretation, and `PRIVACY.md` for transformations. `MANIFEST.json` hashes every public payload file except itself.

Each episode contains an outcome record, an ordered `events.jsonl` timeline, and watch states with visible responses. Shared `inputs/` and `attacks/` contain only referenced, sanitized frozen artifacts. No previous export is grandfathered into this candidate.

Do not pool cohorts merely because model labels match. A death is not proof of a successful injection; zero deaths are not proof of resistance. Exposure, held actuation, restoration, procedural behavior, and crew outcomes are distinct measurements. Incomplete or unreviewed attempts remain outside this repository.

## Offline verification

From the sibling experiment-runtime checkout:

    python -m scripts.publication.verify --output ../biosim-attacker-simulation-experiment-results

A custodian can additionally supply `--private-dir PRIVATE_PROVENANCE --policy PRIVATE_POLICY` for source-level fidelity verification. Neither private input belongs in this repository. No model access is used.

## Rights and status

The cleaned trace contribution is offered under CC BY 4.0, subject to the exceptions in `THIRD_PARTY.md`. Cleaning does not establish ownership of incorporated material or remove third-party rights. Public distribution requires the custodian's rights and privacy review. These are pseudonymized records, not a guarantee against reidentification.
""",
    "SCHEMA.md": """# Trace schema, version 2

`SCHEMA.json` provides public JSON Schema definitions. `SOURCE-SCHEMA.json` documents each source record's retained fields, explicitly mapped fields, and justified private omissions. Unknown source fields are held, never approved merely to reach a target count. Retained measurement trees preserve all nonprivate descendants.

Optional recorded temperature, cell indices, initial habitat state, card settings/identity/plant descriptions, and context-window/compaction measurements are retained. Missing settings are not invented. Context-model labels must be explicitly mapped; unresolved labels are held. Initial setup state is separate from terminal state. Source cell-factor suffixes preserve repeat/treatment labels without exposing the private series/model prefixes.

- `index.json` is the exact exported inventory. Each entry references its outcome, frozen input bundle, and optional attack text.
- `episodes/<episode_id>/outcome.json` records precise public `model` and `model_requested` labels, pseudonymous cohort/route/experiment identifiers, recorded arm/trust/condition, `experiment` parameters, `protocol`, sanitized card evidence, judge selection, counts, and `outcome` measurements. Missing experimental settings are absent, not defaulted to newer values.
- `events.jsonl` preserves source event order with contiguous one-based `sequence`, source event type, and its allowed scientific fields. Tool rows retain actual `ticks`, arguments, result, optional score, and S-band exposure/frame metadata. Exactly one setup and one outcome marker are required. Each full canonical raw marker payload must equal its referenced standalone record before a reference is emitted; disagreements are held. `event_count` counts all rows; `tool_event_count` counts only `event: tool` rows.
- `watches/<turn>.json` retains recorded states, scores, query, return code, timeouts, tool summaries, and recovery indicators. `response` contains `availability`, `format`, final visible `text`, and ordered visible assistant `messages`. Empty responses are not fabricated; JSONL thinking events are omitted. Final text may repeat the last message because these are distinct source fields.
- `inputs/input-<public hash>.json` preserves relevant frozen Markdown, console rules (`.mdc`), and `prompts.json` fields. Source signature files are not published. `attacks/attack-<public hash>.txt` is the cleaned episode-local attack snapshot, not a mutable external script.

Cohort identifiers group source batches; route identifiers distinguish source batch/model/harness combinations. They do not certify identical backend endpoints, model revisions, or providers. Reused cell names are not a deduplication key. Exact outcome/transcript duplicates are checked against their other frozen evidence before collapse.

`judge` is a sanitized eligibility record, not the full private review or a causal success label. All required privacy actions are applied regardless of whether a particular review repeats them. Boolean false is explicit; missing or ambiguous judgments are never treated as false.

Redaction markers identify transformations, not original model language. Numeric scientific values and relative simulator time are retained. Sanitization is not byte identity; public hashes cover only cleaned artifacts. Raw-source bindings and omitted-field accounting remain private.
""",
    "PRIVACY.md": """# Privacy and fidelity transformations

The release excludes personal identifiers, credentials, private paths/hosts/endpoints, routing details, operational diagnostics, authentication and request envelopes, private reasoning streams, and source session histories. Public model labels and experimental parameters remain. Simulation crew names are mapped consistently to Crew-01 through Crew-04; these are labels, not data about real people.

Explicit source schemas retain scientific evidence. Text and object keys additionally undergo private-policy replacements and generic identifier/credential/path cleaning. Encoded private strings are withheld without decoding unrelated public literals. Private provenance binds the selected review and every consumed artifact by original-file hashes. The key, original hashes, mapping, review prose, and private signature policy are never included here.

Visible assistant output is extracted from known JSON or JSONL channels. Separate thought/thinking/analysis fields, JSONL thinking events, request metadata, and diagnostics are not a fallback source. Configured reasoning effort is an experiment parameter, not a reasoning transcript.

Only the explicitly supported frozen input filenames are published; unknown components and unsafe delimiter-encoded names are held. Only the known original pack-signature file is intentionally omitted. Executable/session histories are excluded; classified context-window/compaction measurements remain. A single typed stream record is never treated as an untyped terminal envelope. Basic authentication requires authentication context, and scientific rate units are not treated as file paths. Unknown schema, ambiguous references, unmapped models, unresolved review actions, redaction collisions, and failed fidelity checks require a private hold.

Automated checks do not establish universal anonymity, rights clearance, or scientific validity. Behavioral and textual fingerprints can permit inference. A custodian must independently audit all public files, history, packaging, and third-party rights before remote publication. No remote-publication authorization is implied by this local candidate.
""",
    "LICENSE": """SPDX-License-Identifier: CC-BY-4.0

The original cleaned-trace contribution and original documentation in this repository are licensed under the Creative Commons Attribution 4.0 International License.

License: https://creativecommons.org/licenses/by/4.0/
Legal code: https://creativecommons.org/licenses/by/4.0/legalcode

Attribution: BioSim cleaned experimental traces contributors; identify the repository and version, link the license, and indicate modifications.

This license applies only to rights the contributors can grant. Incorporated third-party material is subject to THIRD_PARTY.md. No warranties or additional privacy, publicity, trademark, patent, or third-party copyright rights are granted.
""",
    "THIRD_PARTY.md": """# Third-party rights and exceptions

CC BY 4.0 covers the contributors' original cleaning, arrangement, annotations, and original documentation, and trace material only to the extent they hold grantable rights. It does not automatically relicense incorporated third-party prompts, model outputs, simulator-derived material, or other upstream material. Those rights remain with their respective holders and may depend on applicable terms or licenses.

This data-only repository does not distribute simulator source, proprietary model/CLI binaries, credentials, or private export provenance. The simulator and experiment-runtime repositories have their own licenses; those licenses must not be inferred from this repository's data license.

The custodian has not asserted blanket third-party rights clearance. Resolve any required upstream permission/attribution before redistribution; material whose rights cannot be established must be withheld or separately licensed. Cleaning and pseudonymization do not cure a rights defect.
""",
    ".gitignore": "__pycache__/\n.pytest_cache/\n*.pyc\n",
}


def write_documents(root: Path) -> None:
    for name, text in DOCUMENTS.items():
        (root / name).write_text(text, encoding="utf-8")
    schemas = {
        "outcome": {"type": "object", "required": ["schema_version", "episode_id", "model", "outcome", "experiment", "protocol", "judge", "event_count", "tool_event_count", "watch_count", "input_ref"], "properties": {"schema_version": {"const": VERSION}, "judge": {"type": "object", "required": ["review_model", "disqualify_from_stats", "content_unsafe", "redaction_actions"], "properties": {"review_model": {"const": REVIEW_MODEL}, "disqualify_from_stats": {"const": False}, "content_unsafe": {"const": False}}}}},
        "event": {"type": "object", "required": ["sequence", "event"], "properties": {"sequence": {"type": "integer", "minimum": 1}, "event": {"enum": sorted(EVENT_FIELDS)}, "ticks": {"type": "number"}, "turn": {"type": "integer"}}, "allOf": [{"if": {"properties": {"event": {"const": "tool"}}}, "then": {"required": ["turn", "ticks", "name", "result"]}}]},
        "watch": {"type": "object", "required": ["turn", "response"], "properties": {"turn": {"type": "integer", "minimum": 1}, "response": {"type": "object", "required": ["availability", "format", "text", "messages"], "properties": {"availability": {"enum": ["present", "empty"]}, "format": {"enum": ["json", "jsonl", "empty"]}, "text": {"type": "string"}, "messages": {"type": "array", "items": {"type": "string"}}}, "additionalProperties": False}}},
        "index": {"type": "array", "items": {"type": "object", "required": ["episode_id", "outcome_ref", "input_ref", "attack_ref"]}},
        "manifest": {"type": "object", "required": ["schema_version", "algorithm", "files"], "properties": {"algorithm": {"const": "sha256"}, "files": {"type": "object", "additionalProperties": {"type": "string", "pattern": "^[a-f0-9]{64}$"}}}},
    }
    schemas["watch"]["properties"]["response"]["properties"].update(num_turns={"type": "integer", "minimum": 0}, stop_reason={"type": "string"})
    schemas["outcome"]["required"] = sorted(OUTCOME_KEYS)
    schemas["outcome"]["additionalProperties"] = False
    for key in OUTCOME_KEYS | OPTIONAL_OUTCOME_KEYS:
        schemas["outcome"]["properties"].setdefault(key, {})
    schemas["index"]["items"].update(required=sorted(INDEX_KEYS), properties={key: {} for key in INDEX_KEYS}, additionalProperties=False)
    schemas["watch"]["additionalProperties"] = False
    for key in WATCH_FIELDS:
        schemas["watch"]["properties"].setdefault(key, {})
    schemas["event"]["additionalProperties"] = False
    for key in {"record_ref"} | {key for fields in EVENT_FIELDS.values() for key in fields}:
        schemas["event"]["properties"].setdefault(key, {})
    dump(root / "SCHEMA.json", {"$schema": "https://json-schema.org/draft/2020-12/schema", "$defs": schemas, "description": "Select the matching $defs entry for each file type."})
    dump(root / "SOURCE-SCHEMA.json", source_contract_document())


def physical_payload(root: Path, on_file=None) -> dict[str, Path]:
    require(root.is_dir() and not root.is_symlink(), "invalid_release_root")
    files = {}
    def failed_walk(_):
        raise Hold("release_io_error")
    for directory, dirs, names in os.walk(root, followlinks=False, onerror=failed_walk):
        parent = Path(directory)
        for name in list(dirs) + names:
            path = parent / name
            require(not path.is_symlink(), "release_symlink")
            if name == ".git":
                require(parent == root, "nested_git_metadata")
                if name in dirs:
                    dirs.remove(name)
                continue
            if name == "MANIFEST.json":
                require(parent == root and path.is_file(), "nested_or_invalid_manifest")
                continue
            is_file = path.is_file()
            require(is_file or path.is_dir(), "nonregular_release_artifact")
            if is_file:
                files[path.relative_to(root).as_posix()] = path
                if on_file is not None:
                    on_file(len(files))
    return files


def manifest(root: Path) -> None:
    files = {name: digest(path) for name, path in sorted(physical_payload(root).items())}
    dump(root / "MANIFEST.json", {"schema_version": VERSION, "algorithm": "sha256", "files": files})


def same(actual, expected, reason):
    require(encoded(actual) == encoded(expected), reason)


def count_value(value, reason):
    require(type(value) is int and value >= 0, reason)


def verify_public(root: Path) -> dict:
    scanned_files = 0
    last_scan = time.monotonic()

    def scan_progress(found):
        nonlocal scanned_files, last_scan
        now = time.monotonic()
        if found == 1 or found - scanned_files >= 1024 or now - last_scan >= 30:
            print(f"public verification scan: {found} files found, 0 episodes checked", file=sys.stderr, flush=True)
            scanned_files, last_scan = found, now

    print("public verification scan: 0 files found, 0 episodes checked", file=sys.stderr, flush=True)
    actual = physical_payload(root, on_file=scan_progress)
    print(f"public verification scan: {len(actual)} files found, 0 episodes checked", file=sys.stderr, flush=True)
    m = loads((root / "MANIFEST.json").read_bytes())
    require(m.get("schema_version") == VERSION and m.get("algorithm") == "sha256", "manifest_schema")
    require(set(m["files"]) == set(actual), "manifest_file_closure")
    require({name for name in actual if "/" not in name} == set(DOCUMENTS) | {"index.json", "COVERAGE.json", "SCHEMA.json", "SOURCE-SCHEMA.json"}, "unexpected_root_payload")
    require(all("/" not in name or name.startswith(("episodes/", "inputs/", "attacks/")) for name in actual), "unexpected_payload_directory")

    checked = set()
    episodes_checked = total_episodes = 0
    last_files = last_episodes = 0
    last_report = time.monotonic()

    def progress(*, force=False):
        nonlocal last_files, last_episodes, last_report
        now = time.monotonic()
        if force or len(checked) - last_files >= 1024 or (episodes_checked == 1 and last_episodes == 0) or episodes_checked - last_episodes >= 50 or now - last_report >= 30:
            print(f"public verification: {len(checked)}/{len(actual)} files hashed, {episodes_checked}/{total_episodes} episodes checked", file=sys.stderr, flush=True)
            last_files, last_episodes, last_report = len(checked), episodes_checked, now

    def check_hash(name, value):
        require(value == m["files"][name], "manifest_digest_mismatch")
        checked.add(name)
        progress()

    def read_json(name):
        data = actual[name].read_bytes()
        check_hash(name, hashlib.sha256(data).hexdigest())
        return loads(data)

    index = read_json("index.json")
    require(isinstance(index, list), "invalid_index")
    total_episodes = len(index)
    progress(force=True)
    for name, path in actual.items():
        if name not in {"index.json", "COVERAGE.json"} and not name.startswith(("episodes/", "inputs/", "attacks/")):
            check_hash(name, digest(path))
    ids, assets, episode_files = set(), set(), set()
    models = collections.Counter()
    cohorts = set()
    events = tools = watches = 0
    for entry in index:
        require(isinstance(entry, dict) and set(entry) == INDEX_KEYS, "invalid_index_fields")
        eid = entry["episode_id"]
        require(isinstance(eid, str) and re.fullmatch(r"episode-[0-9a-f]{24}", eid) is not None, "invalid_public_id")
        require(eid not in ids, "duplicate_public_id")
        ids.add(eid)
        expected_outcome = f"episodes/{eid}/outcome.json"
        require(entry["outcome_ref"] == expected_outcome and expected_outcome in actual, "outcome_reference_mismatch")
        outcome = read_json(expected_outcome)
        require(OUTCOME_KEYS <= set(outcome) <= OUTCOME_KEYS | OPTIONAL_OUTCOME_KEYS, "invalid_outcome_fields")
        require(outcome["schema_version"] == VERSION, "outcome_schema_version")
        for key in INDEX_KEYS - {"outcome_ref"}:
            same(entry[key], outcome[key], "index_outcome_mismatch")
        for key in ("event_count", "tool_event_count", "watch_count", "sband_calls"):
            count_value(outcome[key], "invalid_evidence_count")
        for key in ("model", "model_requested", "cohort_id", "route_id", "arm", "trust", "condition"):
            require(isinstance(outcome[key], str), "invalid_public_metadata_type")
        models[outcome["model"]] += 1
        cohorts.add(outcome["cohort_id"])
        assert_public_fields(outcome)
        judge = outcome["judge"]
        require(judge["review_model"] == REVIEW_MODEL and judge["disqualify_from_stats"] is False and judge["content_unsafe"] is False, "unapproved_public_episode")
        for key, directory in (("input_ref", "inputs/"), ("attack_ref", "attacks/")):
            ref = outcome[key]
            if ref is not None:
                require(isinstance(ref, str) and ref.startswith(directory) and ref in actual, "missing_asset_reference")
                assets.add(ref)
        episode_files.add(expected_outcome)
        event_ref = f"episodes/{eid}/events.jsonl"
        require(event_ref in actual, "missing_event_file")
        episode_files.add(event_ref)
        count = tool_count = sband_count = 0
        markers = collections.Counter()
        event_hash = hashlib.sha256()
        with actual[event_ref].open("rb") as stream:
            for line in stream:
                event_hash.update(line)
                row = loads(line)
                count += 1
                require(type(row.get("sequence")) is int and row["sequence"] == count and row.get("event") in EVENT_FIELDS, "event_sequence_or_type")
                kind = row["event"]
                expected_keys = set(EVENT_FIELDS[kind]) | {"event", "sequence"}
                if kind in {"setup", "outcome"}:
                    expected_keys.add("record_ref")
                    markers[kind] += 1
                    require(row.get("record_ref") == "outcome.json", "invalid_marker_reference")
                require(set(row) <= expected_keys, "invalid_public_event_fields")
                assert_public_fields(row)
                if kind == "tool":
                    require(all(k in row for k in ("turn", "ticks", "name", "result")), "invalid_public_tool")
                    require(type(row["turn"]) is int and type(row["ticks"]) in (int, float), "invalid_tool_numeric_type")
                    tool_count += 1
                    sband_count += row["name"] == "read_sband"
        check_hash(event_ref, event_hash.hexdigest())
        require(dict(markers) == {"setup": 1, "outcome": 1}, "public_marker_cardinality")
        watch_paths = sorted((root / "episodes" / eid / "watches").glob("*.json"))
        turns = set()
        for path in watch_paths:
            w = read_json(path.relative_to(root).as_posix())
            require(set(w).issubset(set(WATCH_FIELDS) | {"response"}), "invalid_public_watch_fields")
            require(type(w["turn"]) is int and w["turn"] not in turns, "duplicate_watch")
            turns.add(w["turn"])
            require(path.name == f'{w["turn"]:04d}.json', "watch_filename_mismatch")
            assert_public_fields(w)
            response = w["response"]
            require({"availability", "format", "text", "messages"} <= set(response) <= {"availability", "format", "text", "messages", "num_turns", "stop_reason"}, "response_schema_mismatch")
            if "num_turns" in response:
                count_value(response["num_turns"], "invalid_response_steps")
            if "stop_reason" in response:
                require(isinstance(response["stop_reason"], str), "invalid_stop_reason")
            require(isinstance(response["text"], str) and isinstance(response["messages"], list) and all(isinstance(x, str) for x in response["messages"]), "response_type_mismatch")
            require(response["format"] in {"json", "jsonl", "empty"}, "response_format_mismatch")
            require(response["availability"] == ("present" if response["text"] or response["messages"] else "empty"), "response_availability_mismatch")
            episode_files.add(path.relative_to(root).as_posix())
        same([count, tool_count, len(watch_paths), sband_count], [outcome["event_count"], outcome["tool_event_count"], outcome["watch_count"], outcome["sband_calls"]], "episode_count_mismatch")
        events += count
        tools += tool_count
        watches += len(watch_paths)
        episodes_checked += 1
        progress()
    require(assets == {name for name in actual if name.startswith(("inputs/", "attacks/"))}, "orphan_asset")
    require(episode_files == {name for name in actual if name.startswith("episodes/")}, "orphan_episode_artifact")
    for name in assets:
        path = actual[name]
        if name.startswith("inputs/"):
            assert_public_fields(read_json(name))
        else:
            check_hash(name, digest(path))
        require(path.stem.split("-", 1)[1] == m["files"][name][:24], "asset_content_address_mismatch")
    coverage = read_json("COVERAGE.json")
    require(coverage["schema_version"] == VERSION and coverage["review_filename"] == REVIEW_NAME and coverage["review_model"] == REVIEW_MODEL, "coverage_schema_mismatch")
    for key in ("outcome_records", "latest_review_records", "approved_before_dedup", "selected_candidates", "duplicates_removed", "exported_episodes", "additional_holds", "event_count", "tool_event_count", "watch_count", "anonymous_cohorts"):
        count_value(coverage[key], "invalid_coverage_count")
    same(coverage["exported_episodes"], len(ids), "coverage_count_mismatch")
    same([coverage["event_count"], coverage["tool_event_count"], coverage["watch_count"]], [events, tools, watches], "coverage_evidence_mismatch")
    same(coverage["models"], dict(models), "coverage_model_mismatch")
    same(coverage["anonymous_cohorts"], len(cohorts), "coverage_cohort_mismatch")
    same(coverage["selected_candidates"], len(ids) + coverage["additional_holds"], "selection_count_closure")
    for counts in (coverage["additional_hold_reasons"], coverage["excluded_or_pending"]):
        require(isinstance(counts, dict), "invalid_coverage_reason_counts")
        for value in counts.values():
            count_value(value, "invalid_coverage_reason_counts")
    same(sum(coverage["additional_hold_reasons"].values()), coverage["additional_holds"], "hold_count_mismatch")
    require(coverage["outcome_records"] >= coverage["latest_review_records"] >= coverage["approved_before_dedup"] >= coverage["selected_candidates"], "coverage_selection_order")
    require(checked == set(actual), "unverified_payload")
    progress(force=True)
    return {"episodes": len(ids), "events": events, "tool_events": tools, "watches": watches, "files": len(actual) + 1}

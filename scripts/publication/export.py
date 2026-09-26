# SPDX-License-Identifier: MIT
"""Fresh offline export. Run with python -m scripts.publication.export --help."""
from __future__ import annotations

import argparse
import collections
import hashlib
import json
import os
import secrets
import shutil
import tempfile
from pathlib import Path

from .common import EVENT_FIELDS, IDENTITY_COMPONENTS, OMISSIONS, OUTCOME_FIELDS, PARAMETER_FIELDS, REVIEW_MODEL, REVIEW_NAME, VERSION, WATCH_FIELDS, Hold, dump, encoded, loads, require
from .privacy import Policy
from .release import manifest, verify_public, write_documents
from .responses import visible
from .selection import Candidate, freeze_evidence, select
from .source_schema import SchemaAudit, marker_matches, public_card, public_compaction, validate_card, validate_fields, validate_outcome, validate_watch


def private_dump(path: Path, value) -> None:
    dump(path, value)
    path.chmod(0o600)


def key_for(directory: Path) -> bytes:
    path = directory / "pseudonym.key"
    if not path.exists():
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        with os.fdopen(fd, "wb") as stream:
            stream.write(secrets.token_bytes(32))
    require(not path.is_symlink(), "private_key_symlink")
    key = path.read_bytes()
    require(len(key) == 32, "invalid_pseudonym_key")
    return key


def factors(cell: str) -> dict:
    parts = cell.split(":")
    arms = ("kill", "life", "proc", "sband", "best-sband", "matched-sband", "control", "no-injection", "attack", "benign", "envelope", "technical")
    arm = next((value for value in arms if value in parts), "unspecified")
    trust = next((value for value in parts if value in {"t0", "t1", "t2", "unlabeled"}), "unspecified")
    condition = "no_injection" if any(value in parts for value in ("control", "no-injection")) else "attack" if "attack" in parts or arm in {"kill", "life", "proc", "sband", "best-sband", "matched-sband"} else arm
    return {"arm": arm, "trust": trust, "condition": condition}


def asset(root: Path, kind: str, data: bytes) -> str:
    suffix = ".txt" if kind == "attack" else ".json"
    directory = "attacks" if kind == "attack" else "inputs"
    ref = f"{directory}/{kind}-{hashlib.sha256(data).hexdigest()[:24]}{suffix}"
    path = root / ref
    path.parent.mkdir(exist_ok=True)
    if path.exists():
        require(path.read_bytes() == data, "public_asset_hash_collision")
    else:
        path.write_bytes(data)
    return ref


def export_inputs(candidate: Candidate, policy: Policy, audit: SchemaAudit | None = None) -> dict:
    identity = candidate.episode / "identity"
    require(identity.is_dir() and not identity.is_symlink(), "missing_frozen_identity")
    components = {}
    for path in sorted(identity.rglob("*")):
        require(not path.is_symlink(), "source_symlink")
        if not path.is_file():
            continue
        relative = path.relative_to(identity).as_posix()
        raw = candidate.source.read(path)
        if relative == "pack.sha256":
            continue
        name = policy.filename(relative)
        require(name == relative and name not in components, "unsafe_identity_filename")
        require(relative in IDENTITY_COMPONENTS, "unknown_identity_component")
        if path.suffix == ".json":
            require(path.name == "prompts.json", "unknown_identity_json")
            value = loads(raw)
            validate_fields("prompts", value, audit)
        else:
            try:
                value = raw.decode("utf-8")
            except UnicodeError as exc:
                raise Hold("invalid_identity_encoding") from exc
        components[name] = policy.clean(value)
    require("prompts.json" in components and any(name.endswith(".mdc") for name in components), "missing_frozen_prompt_components")
    return {"schema_version": VERSION, "components": components}


def export_episode(candidate: Candidate, policy: Policy, root: Path, audit: SchemaAudit | None = None) -> dict:
    ep, source, raw = candidate.episode, candidate.source, candidate.outcome
    policy = policy.for_review(candidate.review_digest)
    actions = policy.review_actions(candidate.review_digest)
    validate_outcome(raw, audit)
    setup = raw["setup"]
    require(isinstance(raw.get("model"), str) and isinstance(raw.get("cell_id"), str), "invalid_episode_metadata")
    model = policy.model(raw["model"])
    card = source.json(ep / "card.json")
    validate_card(card, raw, audit)
    requested = policy.model(card.get("model_requested", raw["model"]))
    eid = policy.opaque("episode", f"{candidate.root_number}:{candidate.relative}")
    relative = Path(candidate.relative).parts
    batch = "/".join(relative[:3] if relative[0] == "hosts" else relative[:1])
    cohort_key = f"{candidate.root_number}:{batch}"
    output = root / "episodes" / eid
    output.mkdir(parents=True)
    inputs = export_inputs(candidate, policy, audit)
    input_ref = asset(root, "input", encoded(inputs))
    attack_ref = None
    attack = ep / "hijack_script.txt"
    if attack.exists():
        attack_ref = asset(root, "attack", policy.text(source.text(attack)).encode("utf-8"))
    elif setup.get("script"):
        raise Hold("missing_frozen_attack")
    parameters = policy.clean({key: setup[key] for key in PARAMETER_FIELDS if key in setup})
    protocol = policy.clean({key: raw[key] for key in ("pack_version", "script_bank") if key in raw})
    protocol["runtime_variant_id"] = policy.opaque("runtime", json.dumps([raw.get("harness"), raw.get("identity_id"), raw.get("pack_version"), setup.get("max_tool_turns"), setup.get("recover_max_turn_watch")], sort_keys=True))
    outcome = policy.clean({key: raw[key] for key in OUTCOME_FIELDS if key in raw})
    compaction = raw.get("compaction")
    if isinstance(compaction, dict):
        outcome["compaction"] = public_compaction(compaction, policy)
    summary = {
        "schema_version": VERSION, "episode_id": eid, "model": model, "model_requested": requested,
        "cohort_id": policy.opaque("cohort", cohort_key),
        "route_id": policy.opaque("route", json.dumps([cohort_key, raw["model"], raw.get("harness")], sort_keys=True)),
        "experiment_series_id": policy.opaque("series", str(raw.get("experiment_id"))),
        **factors(raw["cell_id"]), "cell_factors": policy.clean(raw["cell_id"].split(":")[2:]), "experiment": parameters, "protocol": protocol,
        "card_evidence": public_card(card, policy),
        "outcome": outcome, "input_ref": input_ref, "attack_ref": attack_ref,
        "judge": {"review_model": REVIEW_MODEL, "disqualify_from_stats": False, "content_unsafe": False, "path_redaction_required": candidate.review["path_redaction_required"], "redaction_actions": actions},
    }
    if "habitat" in setup:
        summary["initial_state"] = policy.clean(setup["habitat"])
    markers = collections.Counter()
    event_count = tool_count = sband_count = 0
    with (output / "events.jsonl").open("wb") as stream:
        for _, event in source.rows(ep / "transcript.jsonl"):
            kind = event.get("event")
            require(kind in EVENT_FIELDS, "unknown_event_type")
            validate_fields("event." + kind, event, audit)
            event_count += 1
            public = {"sequence": event_count, "event": kind}
            public.update(policy.clean({key: event[key] for key in EVENT_FIELDS[kind] if key in event}))
            if kind in {"setup", "outcome"}:
                marker_matches(kind, event.get(kind), raw, audit)
                markers[kind] += 1
                public["record_ref"] = "outcome.json"
            if kind == "tool":
                require(all(key in event for key in ("turn", "ticks", "name", "result")), "invalid_tool_event")
                tool_count += 1
                sband_count += event["name"] == "read_sband"
            stream.write(encoded(public))
    require(dict(markers) == {"setup": 1, "outcome": 1}, "transcript_marker_cardinality")
    turns = set()
    for path in sorted((ep / "wakes").glob("*.json")):
        watch = source.json(path)
        require(isinstance(watch, dict) and type(watch.get("turn")) is int and watch["turn"] > 0, "invalid_watch")
        validate_watch(watch, audit)
        turn = watch["turn"]
        require(turn not in turns, "duplicate_watch")
        turns.add(turn)
        response = visible(source.read(path.with_suffix(".stdout")))
        if watch.get("result"):
            require(watch["result"] == response["text"], "visible_result_mismatch")
        public = policy.clean({key: watch[key] for key in WATCH_FIELDS if key in watch})
        public["response"] = policy.clean(response)
        dump(output / "watches" / f"{turn:04d}.json", public)
    require(bool(turns), "missing_watches")
    summary.update(event_count=event_count, tool_event_count=tool_count, watch_count=len(turns), sband_calls=sband_count)
    dump(output / "outcome.json", summary)
    source.unchanged()
    return {"episode_id": eid, "outcome_ref": f"episodes/{eid}/outcome.json", "model": model, "cohort_id": summary["cohort_id"], "route_id": summary["route_id"], "arm": summary["arm"], "trust": summary["trust"], "condition": summary["condition"], "input_ref": input_ref, "attack_ref": attack_ref, "event_count": event_count, "tool_event_count": tool_count, "watch_count": len(turns)}


def export(roots: list[Path], output: Path, private_dir: Path, policy_path: Path, expected_candidates: int | None = None, scratch_dir: Path | None = None) -> dict:
    require(all(root.is_dir() and not root.is_symlink() for root in roots), "invalid_source_root")
    roots = [root.resolve() for root in roots]
    output = output.absolute()
    private_dir = private_dir.absolute()
    require(not output.is_symlink() and not private_dir.is_symlink() and not policy_path.is_symlink(), "unsafe_output_location")
    for root in roots:
        require(not output.resolve().is_relative_to(root) and not root.is_relative_to(output.resolve()), "source_output_overlap")
        require(not private_dir.resolve().is_relative_to(root), "source_private_overlap")
    require(not private_dir.resolve().is_relative_to(output.resolve()) and not policy_path.resolve().is_relative_to(output.resolve()), "private_output_overlap")
    tool_repository = Path(__file__).resolve().parents[2]
    require(not private_dir.resolve().is_relative_to(tool_repository) and not policy_path.resolve().is_relative_to(tool_repository), "private_data_in_tool_repository")
    require(not output.exists() or all(p.name == ".git" for p in output.iterdir()), "output_not_fresh")
    require(not (private_dir / "provenance.json").exists(), "private_provenance_exists")
    private_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    policy = Policy.load(policy_path, key_for(private_dir))
    policy_digest = hashlib.sha256(policy_path.read_bytes()).hexdigest()
    inventory = select(roots)
    private_dump(private_dir / "selection.json", {"source_roots": [str(root) for root in roots], "outcome_count": inventory.outcome_count, "latest_review_count": inventory.latest_review_count, "approved_before_dedup": inventory.approved_before_dedup, "selected_candidates": len(inventory.candidates), "held": inventory.held, "duplicates": inventory.duplicates})
    require(expected_candidates is None or len(inventory.candidates) == expected_candidates, "unexpected_candidate_count")
    index, provenance, additional_holds = [], [], []
    schema_audit = SchemaAudit()
    frozen_failures = {}
    for candidate in inventory.candidates:
        try:
            freeze_evidence(candidate)
        except Hold as exc:
            frozen_failures[candidate.episode] = exc.code
        except OSError:
            frozen_failures[candidate.episode] = "source_io_error"
    with tempfile.TemporaryDirectory(prefix="biosim-trace-export-", dir=scratch_dir) as temporary:
        stage = Path(temporary)
        for candidate in inventory.candidates:
            eid = policy.opaque("episode", f"{candidate.root_number}:{candidate.relative}")
            try:
                if candidate.episode in frozen_failures:
                    raise Hold(frozen_failures[candidate.episode])
                entry = export_episode(candidate, policy, stage, schema_audit)
                index.append(entry)
                provenance.append({"public_id": eid, "source_root": str(candidate.root), "root_number": candidate.root_number, "source": str(candidate.episode), "review_digest": candidate.review_digest, "source_digest": candidate.signature, "files": candidate.source.hashes})
            except Hold as exc:
                additional_holds.append({"source": str(candidate.episode), "reason": exc.code, "details": exc.details, "review_digest": candidate.review_digest, "files": candidate.source.hashes})
                if (stage / "episodes" / eid).exists():
                    shutil.rmtree(stage / "episodes" / eid)
            except (OSError, UnicodeError):
                additional_holds.append({"source": str(candidate.episode), "reason": "source_io_or_encoding_error", "review_digest": candidate.review_digest})
                if (stage / "episodes" / eid).exists():
                    shutil.rmtree(stage / "episodes" / eid)
        used = {entry[key] for entry in index for key in ("input_ref", "attack_ref") if entry[key]}
        for directory in ("inputs", "attacks"):
            for path in (stage / directory).glob("*"):
                if path.relative_to(stage).as_posix() not in used:
                    path.unlink()
        index.sort(key=lambda item: item["episode_id"])
        coverage = {
            "schema_version": VERSION, "status": "local-publication-candidate", "review_filename": REVIEW_NAME, "review_model": REVIEW_MODEL,
            "source_scope": "Explicit local archive roots only; no previous exports or remote fetches.",
            "outcome_records": inventory.outcome_count, "latest_review_records": inventory.latest_review_count,
            "approved_before_dedup": inventory.approved_before_dedup, "selected_candidates": len(inventory.candidates),
            "duplicates_removed": len(inventory.duplicates), "exported_episodes": len(index), "additional_holds": len(additional_holds),
            "excluded_or_pending": dict(collections.Counter(record["reason"] for record in inventory.held)),
            "additional_hold_reasons": dict(collections.Counter(record["reason"] for record in additional_holds)),
            "event_count": sum(entry["event_count"] for entry in index), "tool_event_count": sum(entry["tool_event_count"] for entry in index), "watch_count": sum(entry["watch_count"] for entry in index),
            "models": dict(collections.Counter(entry["model"] for entry in index)), "anonymous_cohorts": len({entry["cohort_id"] for entry in index}),
            "omissions": OMISSIONS, "interpretation": "Episode inventory, not a pooled scientific denominator or an attack-success count.",
        }
        dump(stage / "index.json", index)
        dump(stage / "COVERAGE.json", coverage)
        write_documents(stage)
        manifest(stage)
        verified = verify_public(stage)
        require(hashlib.sha256(policy_path.read_bytes()).hexdigest() == policy_digest, "policy_changed")
        private_dump(private_dir / "additional-holds.json", additional_holds)
        private_dump(private_dir / "provenance.json", {"schema_version": VERSION, "policy_digest": policy_digest, "episodes": provenance, "source_roots": [str(root) for root in roots]})
        private_dump(private_dir / "redactions.json", {"counts": dict(policy.counts), "omitted_fields": dict(policy.omitted_fields)})
        private_dump(private_dir / "source-schema-observations.json", schema_audit.report())
        private_dump(private_dir / "public-verification.json", verified)
        require(not output.exists() or all(p.name == ".git" for p in output.iterdir()), "output_changed")
        output.mkdir(parents=True, exist_ok=True)
        for path in sorted(stage.iterdir()):
            destination = output / path.name
            if path.is_dir():
                shutil.copytree(path, destination)
            else:
                shutil.copyfile(path, destination)
    return {"selected": len(inventory.candidates), "exported": len(index), "additional_holds": len(additional_holds), **verified}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", action="append", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--private-dir", required=True, type=Path)
    parser.add_argument("--policy", required=True, type=Path)
    parser.add_argument("--expected-candidates", type=int)
    parser.add_argument("--scratch-dir", type=Path)
    args = parser.parse_args()
    try:
        result = export(args.source_root, args.output, args.private_dir, args.policy, args.expected_candidates, args.scratch_dir)
    except Hold as exc:
        print(json.dumps({"status": "blocked", "reason": exc.code}))
        return 2
    except (OSError, KeyError, TypeError, ValueError):
        print(json.dumps({"status": "blocked", "reason": "invalid_input_or_io_error"}))
        return 2
    print(json.dumps({"status": "ok", **result}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

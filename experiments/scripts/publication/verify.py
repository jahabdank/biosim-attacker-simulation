# SPDX-License-Identifier: MIT
"""Independent source assertions, numeric invariants, and public packaging checks."""
from __future__ import annotations

import argparse
import collections
import hashlib
import itertools
import json
from pathlib import Path

from .common import CARD_FIELDS, EVENT_FIELDS, IDENTITY_COMPONENTS, OUTCOME_FIELDS, PARAMETER_FIELDS, REVIEW_NAME, VERSION, WATCH_FIELDS, Hold, Source, encoded, loads, require
from .privacy import Policy, blocked_key
from .release import verify_public
from .selection import parse_review, select
from .source_schema import SOURCE_FIELDS, SchemaAudit, validate_card, validate_fields, validate_outcome, validate_watch


def equal(actual, expected, code: str) -> None:
    require(encoded(actual) == encoded(expected), code)


def response_from_source(data: bytes) -> dict:
    if not data.strip():
        return {"availability": "empty", "format": "empty", "text": "", "messages": []}
    try:
        envelope = loads(data)
    except Hold as exc:
        if exc.code != "invalid_json":
            raise
        records = [loads(line) for line in data.splitlines() if line.strip()]
    else:
        require(isinstance(envelope, dict), "fidelity_response_schema")
        if "type" not in envelope:
            validate_fields("terminal_response", envelope)
            require(isinstance(envelope.get("text"), str), "fidelity_response_schema")
            final = envelope["text"]
            result = {"availability": "present" if final else "empty", "format": "json", "text": final, "messages": [final] if final else []}
            if "num_turns" in envelope:
                require(type(envelope["num_turns"]) is int and envelope["num_turns"] >= 0, "fidelity_response_steps")
                result["num_turns"] = envelope["num_turns"]
            if "stopReason" in envelope:
                require(isinstance(envelope["stopReason"], str), "fidelity_stop_reason")
                result["stop_reason"] = envelope["stopReason"]
            return result
        records = [envelope]
    messages, terminal = [], []
    for row in records:
        require(isinstance(row, dict), "fidelity_stream_schema")
        kind = row.get("type")
        if kind in {"system", "user", "thinking", "tool_call"}:
            continue
        if kind == "assistant":
            require(set(row) <= {"type", "message", "session_id", "model_call_id", "timestamp_ms"}, "fidelity_assistant_envelope")
            message = row.get("message")
            require(isinstance(message, dict) and message.get("role") == "assistant" and set(message) <= {"role", "content"}, "fidelity_assistant_role")
            content = message.get("content")
            if isinstance(content, str):
                messages.append(content)
            else:
                require(isinstance(content, list), "fidelity_assistant_content")
                for block in content:
                    require(isinstance(block, dict), "fidelity_assistant_block")
                    if block.get("type") == "text":
                        require(set(block) <= {"type", "text"} and isinstance(block.get("text"), str), "fidelity_visible_text")
                        messages.append(block["text"])
                    else:
                        require(block.get("type") in {"thinking", "reasoning", "tool_use"}, "fidelity_unknown_block")
        elif kind == "result":
            require(set(row) <= {"type", "result", "is_error", "request_id", "session_id", "subtype", "duration_api_ms", "duration_ms", "usage"}, "fidelity_result_envelope")
            require(isinstance(row.get("result"), str) and row.get("is_error", False) is False and row.get("subtype", "success") == "success", "fidelity_terminal_response")
            terminal.append(row["result"])
        else:
            raise Hold("fidelity_unknown_stream_type")
    require(len(terminal) <= 1 and (bool(terminal) or bool(messages)), "fidelity_missing_or_ambiguous_visible_response")
    final = terminal[0] if terminal else messages[-1]
    return {"availability": "present" if final or messages else "empty", "format": "jsonl", "text": final, "messages": messages}


def numeric_evidence(raw, public, policy) -> int:
    def leaves(value, source, path=()):
        if type(value) in (bool, int, float):
            return [(path, type(value).__name__, value)]
        result = []
        if isinstance(value, dict):
            for key, item in value.items():
                if source and blocked_key(key):
                    continue
                result.extend(leaves(item, source, path + (policy.text(key) if source else key,)))
        elif isinstance(value, list):
            for index, item in enumerate(value):
                result.extend(leaves(item, source, path + (index,)))
        return result
    original = sorted(leaves(raw, True), key=lambda item: repr(item[0]))
    actual = sorted(leaves(public, False), key=lambda item: repr(item[0]))
    equal(actual, original, "fidelity_numeric_evidence")
    return len(original)


def checked_compaction(raw, policy):
    result = policy.clean({key: raw[key] for key in SOURCE_FIELDS["compaction"]["retained"] if key in raw})
    if "sessions" in raw:
        result["sessions"] = []
        for session in raw["sessions"]:
            expected = {key: policy.clean(session[key]) for key in SOURCE_FIELDS["compaction_session"]["retained"] if key in session}
            if "primaryModelId" in session:
                expected["primary_model"] = policy.model(session["primaryModelId"])
            result["sessions"].append(expected)
    return result


def checked_card(raw, policy):
    result = {}
    for key in CARD_FIELDS:
        if key not in raw:
            continue
        if key in {"identity_pack", "plant_design"}:
            original = raw[key]
            result[key] = {name: policy.clean(original[name]) for name in SOURCE_FIELDS[key]["retained"] if name in original}
            if key == "identity_pack" and "id" in original:
                result[key]["identity_id"] = policy.opaque("identity", str(original["id"]))
        else:
            result[key] = policy.clean(raw[key])
    return result


def source_counts(output, current, held):
    coverage = loads((output / "COVERAGE.json").read_bytes())
    expected = {
        "outcome_records": current.outcome_count, "latest_review_records": current.latest_review_count,
        "approved_before_dedup": current.approved_before_dedup, "selected_candidates": len(current.candidates),
        "duplicates_removed": len(current.duplicates), "additional_holds": len(held),
        "excluded_or_pending": dict(collections.Counter(row["reason"] for row in current.held)),
        "additional_hold_reasons": dict(collections.Counter(row["reason"] for row in held)),
    }
    for key, value in expected.items():
        equal(coverage[key], value, "fidelity_source_coverage")


def verify_hold(record, policy, candidates):
    require(record["source"] in candidates, "hold_not_selected")
    candidate = candidates[record["source"]]
    require(record["review_digest"] == candidate.review_digest, "hold_review_changed")
    for name, expected in record.get("files", {}).items():
        require(hashlib.sha256(candidate.source.read(Path(name))).hexdigest() == expected, "held_source_changed")
    reason = record["reason"]
    raw = candidate.outcome
    if reason == "unmapped_context_model":
        require(any(row.get("primaryModelId") not in policy.models for row in raw.get("compaction", {}).get("sessions", []) if "primaryModelId" in row), "unjustified_context_model_hold")
        return
    try:
        active = policy.for_review(candidate.review_digest)
        validate_outcome(raw)
        validate_card(candidate.source.json(candidate.episode / "card.json"), raw)
        active.model(raw["model"])
        for path in (candidate.episode / "identity").rglob("*"):
            if path.is_file() and path.name != "pack.sha256":
                name = path.relative_to(candidate.episode / "identity").as_posix()
                require(active.filename(name) == name, "unsafe_identity_filename")
                require(name in IDENTITY_COMPONENTS, "unknown_identity_component")
                if path.name == "prompts.json":
                    validate_fields("prompts", candidate.source.json(path))
        if raw["setup"].get("script"):
            require((candidate.episode / "hijack_script.txt").is_file(), "missing_frozen_attack")
        markers = collections.Counter()
        for _, row in candidate.source.rows(candidate.episode / "transcript.jsonl"):
            kind = row.get("event")
            require(kind in EVENT_FIELDS, "unknown_event_type")
            validate_fields("event." + kind, row)
            if kind in {"setup", "outcome"}:
                markers[kind] += 1
                expected = raw["setup"] if kind == "setup" else raw
                equal(row.get(kind), expected, "transcript_" + kind + "_mismatch")
        require(dict(markers) == {"setup": 1, "outcome": 1}, "transcript_marker_cardinality")
        for path in (candidate.episode / "wakes").glob("*.json"):
            validate_watch(candidate.source.json(path))
            response_from_source(candidate.source.read(path.with_suffix(".stdout")))
    except Hold as exc:
        decoder_reasons = {
            "missing_visible_response": {"fidelity_missing_or_ambiguous_visible_response"},
            "ambiguous_terminal_response": {"fidelity_missing_or_ambiguous_visible_response"},
            "unknown_stdout_event": {"fidelity_unknown_stream_type"},
            "stdout_terminal_error": {"fidelity_terminal_response"},
            "unknown_stdout_schema": {"fidelity_response_schema", "fidelity_stream_schema"},
            "invalid_visible_text": {"fidelity_response_schema", "fidelity_visible_text"},
            "unknown_assistant_envelope_field": {"fidelity_assistant_envelope"},
            "invalid_assistant_message": {"fidelity_assistant_role"},
            "unknown_assistant_message_field": {"fidelity_assistant_role"},
            "invalid_assistant_content": {"fidelity_assistant_content"},
            "invalid_assistant_block": {"fidelity_assistant_block"},
            "unknown_assistant_block": {"fidelity_unknown_block"},
            "unknown_result_envelope_field": {"fidelity_result_envelope"},
            "invalid_terminal_response": {"fidelity_terminal_response"},
            "invalid_response_steps": {"fidelity_response_steps"},
            "invalid_stop_reason": {"fidelity_stop_reason"},
        }
        require(exc.code == reason or exc.code in decoder_reasons.get(reason, set()), "hold_reason_mismatch")
        return
    raise Hold("unverified_hold_reason", details={"reason": reason})


def verify_episode(record, output, base_policy, audit):
    policy = base_policy.for_review(record["review_digest"])
    root, ep = Path(record["source_root"]), Path(record["source"])
    source = Source(root)
    for name, expected_hash in record["files"].items():
        require(hashlib.sha256(source.read(Path(name))).hexdigest() == expected_hash, "fidelity_source_changed")
    review_bytes = source.read(ep / REVIEW_NAME)
    require(hashlib.sha256(review_bytes).hexdigest() == record["review_digest"], "fidelity_review_binding")
    review = parse_review(review_bytes)
    require(review["disqualify_from_stats"] is False and review["content_unsafe"] is False, "fidelity_judge_changed")
    raw = source.json(ep / "outcome.json")
    card = source.json(ep / "card.json")
    validate_outcome(raw, audit)
    validate_card(card, raw, audit)
    eid = record["public_id"]
    require(policy.opaque("episode", f'{record["root_number"]}:{ep.relative_to(root).as_posix()}') == eid, "fidelity_pseudonym_mismatch")
    pub = output / "episodes" / eid
    outcome = loads((pub / "outcome.json").read_bytes())
    expected_outcome = policy.clean({key: raw[key] for key in OUTCOME_FIELDS if key in raw})
    if "compaction" in raw:
        expected_outcome["compaction"] = checked_compaction(raw["compaction"], policy)
    equal(outcome["outcome"], expected_outcome, "fidelity_outcome")
    numeric = 0
    for key in OUTCOME_FIELDS:
        if key in raw:
            numeric += numeric_evidence(raw[key], outcome["outcome"][key], policy)
    if "compaction" in raw:
        numeric += numeric_evidence(raw["compaction"], outcome["outcome"]["compaction"], policy)
    expected_parameters = {key: raw["setup"][key] for key in PARAMETER_FIELDS if key in raw["setup"]}
    equal(outcome["experiment"], policy.clean(expected_parameters), "fidelity_parameters")
    numeric += numeric_evidence(expected_parameters, outcome["experiment"], policy)
    require(("initial_state" in outcome) == ("habitat" in raw["setup"]), "fidelity_initial_state_presence")
    if "habitat" in raw["setup"]:
        equal(outcome["initial_state"], policy.clean(raw["setup"]["habitat"]), "fidelity_initial_state")
        numeric += numeric_evidence(raw["setup"]["habitat"], outcome["initial_state"], policy)
    require(outcome["model"] == policy.model(raw["model"]), "fidelity_model")
    require(outcome["model_requested"] == policy.model(card.get("model_requested", raw["model"])), "fidelity_requested_model")
    equal(outcome["card_evidence"], checked_card(card, policy), "fidelity_card")
    numeric += numeric_evidence({key: card[key] for key in CARD_FIELDS if key in card}, outcome["card_evidence"], policy)
    relative = ep.relative_to(root).parts
    batch = "/".join(relative[:3] if relative[0] == "hosts" else relative[:1])
    cohort_key = f'{record["root_number"]}:{batch}'
    require(outcome["cohort_id"] == policy.opaque("cohort", cohort_key), "fidelity_cohort")
    require(outcome["route_id"] == policy.opaque("route", json.dumps([cohort_key, raw["model"], raw.get("harness")], sort_keys=True)), "fidelity_route")
    require(outcome["experiment_series_id"] == policy.opaque("series", str(raw.get("experiment_id"))), "fidelity_series")
    parts = raw["cell_id"].split(":")
    arm = next((x for x in ("kill", "life", "proc", "sband", "best-sband", "matched-sband", "control", "no-injection", "attack", "benign", "envelope", "technical") if x in parts), "unspecified")
    trust = next((x for x in parts if x in {"t0", "t1", "t2", "unlabeled"}), "unspecified")
    condition = "no_injection" if set(parts) & {"control", "no-injection"} else "attack" if "attack" in parts or arm in {"kill", "life", "proc", "sband", "best-sband", "matched-sband"} else arm
    equal([outcome["arm"], outcome["trust"], outcome["condition"]], [arm, trust, condition], "fidelity_factors")
    equal(outcome["cell_factors"], policy.clean(parts[2:]), "fidelity_cell_factors")
    expected_protocol = policy.clean({key: raw[key] for key in ("pack_version", "script_bank") if key in raw})
    expected_protocol["runtime_variant_id"] = policy.opaque("runtime", json.dumps([raw.get("harness"), raw.get("identity_id"), raw.get("pack_version"), raw["setup"].get("max_tool_turns"), raw["setup"].get("recover_max_turn_watch")], sort_keys=True))
    equal(outcome["protocol"], expected_protocol, "fidelity_protocol")
    equal(outcome["judge"], {"review_model": review["review_model"], "disqualify_from_stats": False, "content_unsafe": False, "path_redaction_required": review["path_redaction_required"], "redaction_actions": policy.review_actions(record["review_digest"])}, "fidelity_judge")
    count = tools = sband_calls = 0
    markers = collections.Counter()
    with (pub / "events.jsonl").open("rb") as stream:
        sentinel = object()
        for raw_pair, public_line in itertools.zip_longest(source.rows(ep / "transcript.jsonl"), stream, fillvalue=sentinel):
            require(raw_pair is not sentinel and public_line is not sentinel, "fidelity_event_length")
            _, event = raw_pair
            actual = loads(public_line)
            count += 1
            kind = event["event"]
            require(kind in EVENT_FIELDS, "fidelity_unknown_event")
            validate_fields("event." + kind, event, audit)
            expected = {"sequence": count, "event": kind}
            for key in EVENT_FIELDS[kind]:
                if key in event:
                    expected[key] = policy.clean(event[key])
            if kind in ("setup", "outcome"):
                if kind == "setup":
                    validate_fields("setup", event.get(kind), audit)
                    referenced = raw["setup"]
                else:
                    validate_outcome(event.get(kind), audit)
                    referenced = raw
                equal(event[kind], referenced, "fidelity_transcript_" + kind)
                markers[kind] += 1
                expected["record_ref"] = "outcome.json"
            equal(actual, expected, "fidelity_event_fields")
            for key in EVENT_FIELDS[kind]:
                if key in event:
                    numeric += numeric_evidence(event[key], actual[key], policy)
            tools += kind == "tool"
            sband_calls += kind == "tool" and event.get("name") == "read_sband"
    require(dict(markers) == {"setup": 1, "outcome": 1}, "fidelity_marker_cardinality")
    require(outcome["sband_calls"] == sband_calls, "fidelity_sband_count")
    watch_count = 0
    for path in sorted((ep / "wakes").glob("*.json")):
        raw_watch = source.json(path)
        validate_watch(raw_watch, audit)
        actual = loads((pub / "watches" / f'{raw_watch["turn"]:04d}.json').read_bytes())
        expected = policy.clean({key: raw_watch[key] for key in WATCH_FIELDS if key in raw_watch})
        response = response_from_source(source.read(path.with_suffix(".stdout")))
        if raw_watch.get("result"):
            equal(raw_watch["result"], response["text"], "fidelity_visible_result")
        expected["response"] = policy.clean(response)
        equal(actual, expected, "fidelity_watch_or_response")
        numeric += numeric_evidence(response, actual["response"], policy)
        for key in WATCH_FIELDS:
            if key in raw_watch:
                numeric += numeric_evidence(raw_watch[key], actual[key], policy)
        watch_count += 1
    equal([outcome["event_count"], outcome["tool_event_count"], outcome["watch_count"]], [count, tools, watch_count], "fidelity_counts")
    expected_components = {}
    for path in sorted((ep / "identity").rglob("*")):
        require(not path.is_symlink(), "source_symlink")
        if not path.is_file():
            continue
        name = path.relative_to(ep / "identity").as_posix()
        if name == "pack.sha256":
            continue
        require(policy.filename(name) == name, "unsafe_identity_filename")
        require(name in IDENTITY_COMPONENTS, "unknown_identity_component")
        value = source.json(path) if path.suffix == ".json" else source.text(path)
        if path.suffix == ".json":
            validate_fields("prompts", value, audit)
        expected_components[name] = policy.clean(value)
    actual_inputs = loads((output / outcome["input_ref"]).read_bytes())
    equal(actual_inputs, {"schema_version": VERSION, "components": expected_components}, "fidelity_frozen_inputs")
    attack = ep / "hijack_script.txt"
    if attack.exists():
        require(outcome["attack_ref"] is not None, "fidelity_missing_attack")
        equal((output / outcome["attack_ref"]).read_text(), policy.text(source.text(attack)), "fidelity_attack")
    else:
        require(outcome["attack_ref"] is None, "fidelity_extra_attack")
    source.unchanged()
    return count, watch_count, numeric


def verify_private(output: Path, private_dir: Path, policy_path: Path) -> dict:
    public_report = verify_public(output)
    provenance = loads((private_dir / "provenance.json").read_bytes())
    require(hashlib.sha256(policy_path.read_bytes()).hexdigest() == provenance["policy_digest"], "fidelity_policy_changed")
    policy = Policy.load(policy_path, (private_dir / "pseudonym.key").read_bytes())
    index = loads((output / "index.json").read_bytes())
    records = provenance["episodes"]
    require({entry["episode_id"] for entry in index} == {record["public_id"] for record in records}, "fidelity_mapping_closure")
    current = select([Path(root) for root in provenance["source_roots"]])
    candidates = {str(candidate.episode): candidate for candidate in current.candidates}
    held = loads((private_dir / "additional-holds.json").read_bytes())
    released_sources = {record["source"] for record in records}
    held_sources = {record["source"] for record in held}
    require(len(held_sources) == len(held) and len(released_sources) == len(records), "duplicate_provenance_source")
    require(not released_sources & held_sources and set(candidates) == released_sources | held_sources, "fidelity_selection_closure")
    source_counts(output, current, held)
    for record in held:
        verify_hold(record, policy, candidates)
    checked = event_total = watch_total = numeric_total = 0
    audit = SchemaAudit()
    for record in records:
        require(record["source_digest"] == candidates[record["source"]].signature, "fidelity_source_digest")
        try:
            events, watches, numbers = verify_episode(record, output, policy, audit)
        except Hold as exc:
            exc.details.setdefault("public_id", record["public_id"])
            raise
        checked += 1
        event_total += events
        watch_total += watches
        numeric_total += numbers
    return {**public_report, "source_verified_episodes": checked, "source_verified_events": event_total, "source_verified_watches": watch_total, "numeric_leaves_verified": numeric_total, "marker_payloads_verified": checked * 2, "additional_holds": len(held), "holds_verified": len(held), "source_schema_records_verified": sum(audit.records.values())}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--private-dir", type=Path)
    parser.add_argument("--policy", type=Path)
    parser.add_argument("--report", type=Path, help="Private verification report, outside the release.")
    args = parser.parse_args()
    try:
        require(bool(args.private_dir) == bool(args.policy), "private_verification_arguments")
        if args.report:
            require(not args.report.resolve().is_relative_to(args.output.resolve()), "private_report_in_release")
        result = verify_private(args.output, args.private_dir, args.policy) if args.private_dir else verify_public(args.output)
    except Hold as exc:
        result = {"status": "failed", "reason": exc.code}
        if args.report and not args.report.resolve().is_relative_to(args.output.resolve()):
            args.report.parent.mkdir(parents=True, exist_ok=True)
            args.report.write_bytes(encoded({**result, "details": exc.details}))
            args.report.chmod(0o600)
        print(json.dumps(result))
        return 2
    except (OSError, KeyError, TypeError):
        print(json.dumps({"status": "failed", "reason": "missing_or_invalid_artifact"}))
        return 2
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_bytes(encoded({"status": "ok", **result}))
        args.report.chmod(0o600)
    print(json.dumps({"status": "ok", **result}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

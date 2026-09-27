# SPDX-License-Identifier: MIT
"""Closed source-record contracts; retained evidence trees are recursively cleaned."""
from __future__ import annotations

import collections
from dataclasses import dataclass, field

from .common import CARD_FIELDS, EVENT_FIELDS, OUTCOME_FIELDS, PARAMETER_FIELDS, PROMPT_FIELDS, WATCH_FIELDS, Hold, encoded, require
from .privacy import blocked_key


def spec(retained=(), mapped=None, omitted=None):
    return {"retained": tuple(retained), "mapped": mapped or {}, "omitted": omitted or {}}


SOURCE_FIELDS = {
    "outcome": spec(OUTCOME_FIELDS, {
        "setup": "Validated experiment settings, initial_state and checked duplicate identifiers.",
        "compaction": "Validated context/compaction measurements with private session locations removed.",
        "model": "Explicit public model label.", "harness": "Pseudonymous route/runtime distinction.",
        "experiment_id": "Pseudonymous experiment_series_id.", "cell_id": "Arm/trust/condition and retained cell_factors.",
        "pack_version": "protocol.pack_version.", "script_bank": "protocol.script_bank.", "identity_id": "Pseudonymous runtime variant and frozen inputs.",
    }, {"operator": "Private driver identifier.", "soul_sha256": "Original-file signature.", "ended_utc": "Absolute operational wall clock."}),
    "setup": spec(PARAMETER_FIELDS, {
        "habitat": "initial_state, without fabricated defaults.",
        **{key: "Checked against the corresponding standalone outcome field." for key in ("model", "harness", "experiment_id", "cell_id", "pack_version", "script_bank", "identity_id")},
    }, {
        **{key: "Private runtime path; frozen local inputs and card evidence are used instead." for key in ("config", "script", "room_path", "transcript", "cursor_workspace", "grok_home", "docker_workspace", "identity", "card")},
        "biosim_url": "Private service endpoint.", "operator": "Private driver identifier.",
        "run_id": "Operational run identifier.", "sim_id": "Operational simulator identifier.", "cursor_watch_id": "Private session identifier.",
        "docker": "Container-launch diagnostic; not a simulator measurement.", "clock_epoch_utc": "Absolute clock origin; relative simulator time is retained.",
        "started_utc": "Absolute operational wall clock.", "soul_sha256": "Original-file signature.",
    }),
    "card": spec(CARD_FIELDS, {
        **{key: "Checked against the standalone outcome field before pseudonymization." for key in ("model", "harness", "experiment_id", "cell_id", "pack_version", "script_bank", "identity_id")},
        "model_requested": "Explicit public requested-model label, separate from actual model.",
    }, {
        **{key: "Original-file signature." for key in ("soul_sha256", "identity_sha256", "script_sha256", "plant_sha256")},
        **{key: "Private source path; frozen local evidence is used instead." for key in ("script_src", "config_src", "identity_dir")},
        "operator": "Private driver identifier.", "run_id": "Operational run identifier.",
    }),
    "identity_pack": spec(("kind", "title", "summary", "pack_version"), {"id": "Pseudonymous identity identifier."}, {
        key: "Original-file signature." for key in ("agents_sha256", "identity_sha256", "soul_sha256", "station_sha256")
    }),
    "plant_design": spec(("id", "kind", "title", "volumes", "backup_vccr_power", "run_till_crew_death", "kill_window_96h"), omitted={"file": "Private plant source path.", "sha256": "Original-file signature."}),
    "compaction": spec(("n_sessions", "any_compaction", "unverified"), {"sessions": "Ordered context summaries; no private session histories."}),
    "compaction_session": spec(("compactionCount", "contextTokensUsed", "contextWindowTokens", "totalTokensBeforeCompaction", "turnCount"), {"primaryModelId": "Explicit public context-model label; unmapped labels are held."}, {"src": "Private session-file location."}),
    "prompts": spec(PROMPT_FIELDS),
    "watch": spec(WATCH_FIELDS, {"result": "Checked against the extracted visible result when nonempty."}, {"session": "Private session identifier.", "stderr_tail": "Operational diagnostics.", "tool_events": "Raw CLI request/response envelopes and internal tool operations; primary executed BioSim calls/results remain in events.jsonl and tools."}),
    "terminal_response": spec(("text", "num_turns"), {"stopReason": "Recorded stop_reason alongside the visible response."}, omitted={
        "thought": "Private reasoning channel.",
        "sessionId": "Private session identifier.", "requestId": "Private request identifier.",
        "usage": "Provider usage envelope.", "modelUsage": "Provider usage/routing envelope.",
        "total_cost_usd": "Billing diagnostic.", "total_cost_usd_ticks": "Billing diagnostic.",
    }),
}
for kind, fields in EVENT_FIELDS.items():
    mapped = {kind: "Full canonical payload equality is required before replacing this marker with a reference."} if kind in {"setup", "outcome"} else {}
    omitted = {"utc": "Absolute operational wall clock."}
    if kind in {"turn_start", "turn_end"}:
        omitted["session"] = "Private session identifier."
    if kind == "tool":
        omitted["sim_id"] = "Operational simulator identifier."
    SOURCE_FIELDS["event." + kind] = spec(("event", *fields), mapped, omitted)

PATH_FIELDS = {
    "setup": {"config", "script", "room_path", "transcript", "cursor_workspace", "grok_home", "docker_workspace", "identity", "card", "biosim_url"},
    "card": {"script_src", "config_src", "identity_dir"},
    "plant_design": {"file"}, "compaction_session": {"src"},
}


@dataclass
class SchemaAudit:
    fields: collections.Counter = field(default_factory=collections.Counter)
    records: collections.Counter = field(default_factory=collections.Counter)

    def record(self, name, key, category):
        self.fields[(name, key, category)] += 1

    def report(self):
        return {"records": dict(self.records), "fields": [{"schema": name, "field": key, "disposition": category, "occurrences": count} for (name, key, category), count in sorted(self.fields.items())]}


def validate_fields(name: str, value, audit: SchemaAudit | None = None):
    require(name in SOURCE_FIELDS and isinstance(value, dict), "invalid_source_record")
    contract = SOURCE_FIELDS[name]
    categories = {key: category for category in ("retained", "mapped", "omitted") for key in contract[category]}
    require(sum(len(contract[c]) for c in contract) == len(categories), "overlapping_source_contract")
    unknown = [key for key in value if key not in categories and not blocked_key(key)]
    if unknown:
        raise Hold("unclassified_source_field", details={"schema": name, "fields": sorted(unknown)})
    for key in PATH_FIELDS.get(name, ()):
        if key in value and value[key] is not None and not isinstance(value[key], str):
            raise Hold("unclassified_source_structure", details={"schema": name, "field": key})
    if name == "setup" and "docker" in value:
        require(type(value["docker"]) is bool, "invalid_container_diagnostic")
    if name in {"setup", "card"} and "temperature" in value:
        require(type(value["temperature"]) in (int, float), "invalid_temperature")
    if audit is not None:
        audit.records[name] += 1
        for key in value:
            audit.record(name, key, categories.get(key, "omitted_private_key"))
    return value


def validate_outcome(value, audit=None):
    validate_fields("outcome", value, audit)
    validate_fields("setup", value["setup"], audit)
    for key in SOURCE_FIELDS["setup"]["mapped"]:
        if key != "habitat" and key in value["setup"]:
            require(key in value and encoded(value["setup"][key]) == encoded(value[key]), "setup_metadata_mismatch")
    if "compaction" in value:
        compaction = validate_fields("compaction", value["compaction"], audit)
        if "sessions" in compaction:
            require(isinstance(compaction["sessions"], list), "invalid_compaction_sessions")
            for session in compaction["sessions"]:
                validate_fields("compaction_session", session, audit)


def validate_card(card, outcome, audit=None):
    validate_fields("card", card, audit)
    for key in SOURCE_FIELDS["card"]["mapped"]:
        if key != "model_requested" and key in card:
            require(key in outcome and encoded(card[key]) == encoded(outcome[key]), "card_metadata_mismatch")
    for key in ("identity_pack", "plant_design"):
        if key in card:
            validate_fields(key, card[key], audit)


def validate_watch(value, audit=None):
    validate_fields("watch", value, audit)
    if "tools" in value:
        require(isinstance(value["tools"], list), "invalid_watch_tools")
        for row in value["tools"]:
            validate_fields("event.tool", row, audit)
            require(row.get("event") == "tool", "invalid_watch_tool_event")
    if "tool_events" in value:
        require(isinstance(value["tool_events"], list), "invalid_cli_tool_envelopes")
        for row in value["tool_events"]:
            require(isinstance(row, dict) and row.get("type") == "tool_call", "invalid_cli_tool_envelope")
            unknown = set(row) - {"type", "event", "name"}
            if unknown:
                raise Hold("unclassified_cli_tool_envelope", details={"fields": sorted(unknown)})
            require(row.get("name") is None or isinstance(row["name"], str), "invalid_cli_tool_name")
            event = row.get("event")
            require(isinstance(event, dict) and event.get("type") == "tool_call", "invalid_cli_tool_envelope")
            unknown = set(event) - {"type", "subtype", "call_id", "model_call_id", "session_id", "timestamp_ms", "tool_call"}
            if unknown:
                raise Hold("unclassified_cli_tool_envelope", details={"fields": ["event." + key for key in sorted(unknown)]})


def marker_matches(kind: str, marker, outcome, audit=None):
    if kind == "setup":
        validate_fields("setup", marker, audit)
        expected = outcome["setup"]
    else:
        validate_outcome(marker, audit)
        expected = outcome
    require(encoded(marker) == encoded(expected), "transcript_" + kind + "_mismatch")


def public_compaction(value, policy):
    result = policy.clean({key: value[key] for key in SOURCE_FIELDS["compaction"]["retained"] if key in value})
    if "sessions" in value:
        result["sessions"] = []
        for row in value["sessions"]:
            public = policy.clean({key: row[key] for key in SOURCE_FIELDS["compaction_session"]["retained"] if key in row})
            if "primaryModelId" in row:
                try:
                    public["primary_model"] = policy.model(row["primaryModelId"])
                except Hold as exc:
                    raise Hold("unmapped_context_model") from exc
            result["sessions"].append(public)
    return result


def public_card(card, policy):
    result = policy.clean({key: card[key] for key in CARD_FIELDS if key in card and key not in {"identity_pack", "plant_design"}})
    for key in ("identity_pack", "plant_design"):
        if key in card:
            value = card[key]
            result[key] = policy.clean({name: value[name] for name in SOURCE_FIELDS[key]["retained"] if name in value})
            if key == "identity_pack" and "id" in value:
                result[key]["identity_id"] = policy.opaque("identity", str(value["id"]))
    return result


def source_contract_document():
    from .common import IDENTITY_COMPONENTS
    from .privacy import BLOCKED_KEYS
    return {
        "schema_version": 2,
        "records": SOURCE_FIELDS,
        "recursive_private_keys_normalized": sorted(BLOCKED_KEYS),
        "identity_components": {"retained": sorted(IDENTITY_COMPONENTS), "omitted": {"pack.sha256": "Original signature, privately bound but never released."}},
        "omitted_cli_tool_event_wrapper": {"fields": ["type", "name", "event"], "required_type": "tool_call", "event_fields": ["type", "subtype", "call_id", "model_call_id", "session_id", "timestamp_ms", "tool_call"], "event_type": "tool_call", "purpose": "Validated private CLI envelope mirror, not the primary simulator tool timeline."},
        "stream_records": {
            "assistant": {"retained": ["message.content text blocks"], "validated": ["type", "message.role"], "omitted": ["session_id", "model_call_id", "timestamp_ms", "non-text thinking/reasoning/tool-use blocks"]},
            "result": {"retained": ["result"], "validated": ["type", "is_error", "subtype"], "omitted": ["request_id", "session_id", "duration_api_ms", "duration_ms", "usage"]},
            "whole_record_omissions": {name: "Private envelope/channel; scientific queries and executed calls are retained from the primary episode timeline." for name in ("system", "user", "thinking", "tool_call")},
        },
        "observed_nested_private_locations": {
            "outcome.turns[].session": "Private CLI session identifier; turn measurements remain.",
            "watch.tools[].sim_id": "Private simulator process handle, not simulator time.",
            "watch.tools[].utc": "Absolute operational timestamp; actual ticks remain.",
            "watch.tool_events": "Validated raw CLI tool_call envelopes, including request/session IDs, absolute timestamps and private internal file operations; primary executed tool events are retained separately.",
        },
        "recursive_evidence": "Retained states, scores, arguments, results and measurements keep all nonprivate descendants; these are not projected to a smaller scientific field list.",
        "private_key_rule": "Explicit normalized credential, authentication, routing, request/session and reasoning keys are omitted recursively. Unknown source-record fields are held, not classified by substring.",
        "markers": "Exactly one setup and one outcome marker; full canonical raw payload equality with the referenced records is required before a reference is emitted.",
    }

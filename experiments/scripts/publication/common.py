# SPDX-License-Identifier: MIT
"""Publication schemas and contained, deterministic file access."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

REVIEW_NAME = "TRACE-REVIEW.grok-4-7-high.md"
REVIEW_MODEL = "grok-4.7-high"
VERSION = 2
EVENT_FIELDS = {
    "setup": (),
    "outcome": (),
    "benign_deviation": ("applied",),
    "turn_start": ("turn", "habitat", "query", "score"),
    "tool": ("turn", "ticks", "name", "args", "arguments", "result", "sband", "score"),
    "turn_end": ("turn", "habitat_after_tick", "habitat_after_wake", "n_tools", "returncode", "score", "watch_cap_recovered"),
}
WATCH_FIELDS = ("turn", "query", "returncode", "timed_out", "habitat_before", "habitat_after_wake", "habitat_after_tick", "score", "tools_compact", "tools", "n_events", "watch_cap_recovered")
OUTCOME_FIELDS = ("status", "incomplete", "incomplete_reason", "n_dead", "n_crew", "score", "habitat", "crew", "uplink", "turns", "mcp_unattached", "benign", "watch_cap_recoveries")
PARAMETER_FIELDS = ("probe", "interrupt_p", "hijack_after_wakes", "seed", "turns", "ticks_per_turn", "warmup_hours", "mode", "stability", "max_tool_turns", "recover_max_turn_watch", "reasoning_effort", "cell_index", "temperature")
CARD_FIELDS = ("plant_design_id", "plant_contract_id", "plant_design", "start_prompt", "turn_prompt_example", "cursor_rule", "cell_index", "mode", "stability", "probe", "interrupt_p", "seed", "temperature", "identity_pack")
PROMPT_FIELDS = ("pack_version", "script_bank", "mode", "start_prompt", "turn_prompt_template", "stop_rule")
INPUT_SUFFIXES = {".md", ".mdc", ".json"}
IDENTITY_COMPONENTS = {"AGENTS.md", "CLAUDE.md", "SOUL.md", "STATION.md", "skills/station-eclss/SKILL.md", "eclss-console.mdc", "prompts.json"}
OMISSIONS = [
    "Authentication, provider/request envelopes, routing, absolute wall-clock identifiers and operational diagnostics.",
    "Private thought/thinking/analysis streams and source session histories; configured reasoning effort is retained.",
    "Original paths, original-file signatures, private selection notes, source maps and pseudonym keys.",
    "Unselected and missing-outcome attempts; absence is not evidence of attack resistance.",
]


class Hold(ValueError):
    """A stable reason code; never include raw content in public error messages."""

    def __init__(self, code: str, *, details: dict | None = None):
        self.code = code
        self.details = details or {}
        super().__init__(code)


def require(condition: bool, code: str) -> None:
    if not condition:
        raise Hold(code)


def pairs_unique(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, "duplicate_json_key")
        result[key] = value
    return result


def loads(text: str | bytes):
    try:
        return json.loads(text, object_pairs_hook=pairs_unique, parse_constant=lambda _: (_ for _ in ()).throw(Hold("nonfinite_json")))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise Hold("invalid_json") from exc


def encoded(value) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n").encode("utf-8")


def dump(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(encoded(value))


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def contained(root: Path, path: Path) -> Path:
    require(not root.is_symlink(), "source_symlink")
    root = root.resolve()
    try:
        relative = path.absolute().relative_to(root)
    except ValueError as exc:
        raise Hold("path_escape") from exc
    current = root
    for part in relative.parts:
        require(part not in (".", ".."), "path_escape")
        current = current / part
        require(not current.is_symlink(), "source_symlink")
    require(current.resolve().is_relative_to(root), "path_escape")
    return current


class Source:
    def __init__(self, root: Path):
        self.root = root.resolve()
        self.hashes: dict[str, str] = {}

    def file(self, path: Path) -> Path:
        path = contained(self.root, path)
        require(path.is_file(), "missing_source_file")
        return path

    def remember(self, path: Path, value: str) -> None:
        previous = self.hashes.get(str(path))
        require(previous is None or previous == value, "source_changed")
        self.hashes[str(path)] = value

    def read(self, path: Path) -> bytes:
        path = self.file(path)
        data = path.read_bytes()
        self.remember(path, hashlib.sha256(data).hexdigest())
        return data

    def text(self, path: Path) -> str:
        try:
            return self.read(path).decode("utf-8")
        except UnicodeError as exc:
            raise Hold("invalid_utf8") from exc

    def json(self, path: Path):
        return loads(self.read(path))

    def rows(self, path: Path):
        path = self.file(path)
        h = hashlib.sha256()
        with path.open("rb") as stream:
            for number, line in enumerate(stream, 1):
                h.update(line)
                if line.strip():
                    row = loads(line)
                    require(isinstance(row, dict), "invalid_event_object")
                    yield number, row
        self.remember(path, h.hexdigest())

    def unchanged(self) -> None:
        for name, expected in self.hashes.items():
            path = self.file(Path(name))
            require(digest(path) == expected, "source_changed")

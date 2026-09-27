"""Versioned, self-contained experiment manifests."""
from __future__ import annotations
import hashlib
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def input_path(value: str) -> Path:
    path = (ROOT / value).resolve()
    if Path(value).is_absolute() or not path.is_relative_to(ROOT):
        raise ValueError("manifest inputs must be repository-relative")
    if not path.exists():
        raise ValueError(f"missing manifest input: {value}")
    return path


def load_manifest(path: Path) -> dict:
    data = json.loads(path.read_text())
    if data.get("schema_version") != 1 or not data.get("jobs"):
        raise ValueError("unsupported or empty manifest")
    ids = set()
    for job in data["jobs"]:
        if not re.fullmatch(r"[A-Za-z0-9_.-]+", job["model"]):
            raise ValueError("invalid model label")
        if job["job_id"] in ids:
            raise ValueError("duplicate job id")
        ids.add(job["job_id"])
        if job["route"] not in {"api", "subscription"}:
            raise ValueError("unknown route kind")
        if job["trust"] not in {"t0", "t1", "t2", "unlabeled"}:
            raise ValueError("unknown trust")
        for key in ("max_tool_turns", "turns", "hours_per_watch", "context_window", "max_completion_tokens", "transient_tries"):
            if key == "max_completion_tokens" and job["route"] == "subscription" and job[key] is None:
                continue
            if type(job[key]) is not int or job[key] < 1:
                raise ValueError(f"invalid {key}")
        identity = input_path(job["identity_dir"])
        for name in ("SOUL.md", "AGENTS.md", "STATION.md", "skills/station-eclss/SKILL.md"):
            if not (identity / name).is_file():
                raise ValueError("incomplete identity")
        if job.get("script_src"):
            source = input_path(job["script_src"])
            if hashlib.sha256(source.read_bytes()).hexdigest() != job["script_sha256"]:
                raise ValueError("script digest mismatch")
        if job["protocol_version"] == "v2-32turn-recovery" and (job["max_tool_turns"] != 32 or not job["recover_max_turn_watch"]):
            raise ValueError("inconsistent v2 protocol")
    return data


def resolve_job(job: dict) -> dict:
    resolved = dict(job)
    for key in ("identity_dir", "script_src"):
        if job.get(key):
            resolved[key] = str(input_path(job[key]))
    return resolved

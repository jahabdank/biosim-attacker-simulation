"""Per-episode record: setup card, JSONL transcript, raw wakes, final plant."""

from __future__ import annotations

from pathlib import Path as _ArchivePath
import sys as _archive_sys
_archive_sys.path.insert(0, str(next(p for p in _ArchivePath(__file__).resolve().parents if (p / "archive_gate.py").is_file())))
from archive_gate import require_enabled, path as _archive_path, setting as _archive_setting, runtime_root as _archive_root
require_enabled()


import fcntl
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def maybe_json(value: Any) -> Any:
    """Parse a JSON string; leave anything else alone."""
    if not isinstance(value, str):
        return value
    text = value.strip()
    if not text or text[0] not in "{[":
        return value
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return value


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def append_jsonl(path: Path, payload: dict[str, Any]) -> None:
    """Append one JSON object. flock so the driver and MCP do not interleave."""
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(payload, default=str) + "\n"
    with path.open("a", encoding="utf-8") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        handle.write(line)
        handle.flush()


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    out: list[dict[str, Any]] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict):
            out.append(obj)
    return out


def record_tool(
    path: Path,
    name: str,
    args: dict[str, Any],
    result: Any,
    *,
    turn: int = 0,
    sim_id: int | None = None,
    ticks: int | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    rec: dict[str, Any] = {
        "event": "tool",
        "utc": utc_now(),
        "name": name,
        "args": args,
        "result": maybe_json(result) if isinstance(result, str) else result,
        "turn": turn,
        "sim_id": sim_id,
        "ticks": ticks,
    }
    if extra:
        rec.update(extra)
    append_jsonl(path, rec)
    return rec


def tools_for_turn(path: Path, turn: int) -> list[dict[str, Any]]:
    return [
        ev
        for ev in load_jsonl(path)
        if ev.get("event") == "tool" and ev.get("turn") == turn
    ]


def compact_tools(tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Short per-turn index: name, args, and what changed / what came back."""
    out: list[dict[str, Any]] = []
    for ev in tools:
        row: dict[str, Any] = {
            "name": ev.get("name"),
            "args": ev.get("args") or {},
            "ticks": ev.get("ticks"),
        }
        if ev.get("sband"):
            row["sband"] = ev["sband"]
        result = ev.get("result")
        if ev.get("name") == "set_flow":
            row["wrote"] = ev.get("args") or {}
            row["got"] = result
        elif ev.get("name") == "read_sband" and isinstance(result, dict):
            row["got"] = {
                "frame": result.get("frame"),
                "text": result.get("text"),
            }
        elif ev.get("name") == "read_habitat" and isinstance(result, dict):
            row["got"] = {
                "hours": result.get("hours"),
                "n_dead": result.get("n_dead"),
                "crew_alive": result.get("crew_alive"),
                "cabin": result.get("cabin"),
            }
        else:
            row["got"] = result
        out.append(row)
    return out


def iter_json_objects(blob: str) -> list[dict[str, Any]]:
    """Pull JSON objects from stream-json lines or a single result object."""
    out: list[dict[str, Any]] = []
    decoder = json.JSONDecoder()
    text = blob or ""
    idx = 0
    while idx < len(text):
        start = text.find("{", idx)
        if start < 0:
            break
        try:
            obj, end = decoder.raw_decode(text, start)
        except json.JSONDecodeError:
            idx = start + 1
            continue
        if isinstance(obj, dict):
            out.append(obj)
        idx = end
    return out


def _toolish(ev: dict[str, Any]) -> dict[str, Any] | None:
    kind = str(ev.get("type") or ev.get("event") or "")
    fn = ev.get("function") if isinstance(ev.get("function"), dict) else {}
    tool_call = ev.get("toolCall") if isinstance(ev.get("toolCall"), dict) else {}
    name = (
        ev.get("name")
        or ev.get("tool")
        or fn.get("name")
        or tool_call.get("name")
        or tool_call.get("tool")
    )
    if kind in {"tool_call", "tool_use", "tool_result"} or (
        name and "tool" in kind.lower()
    ):
        return {"type": kind, "name": name, "event": ev}
    message = ev.get("message") if isinstance(ev.get("message"), dict) else {}
    content = message.get("content")
    if isinstance(content, list):
        for item in content:
            if not isinstance(item, dict):
                continue
            item_type = str(item.get("type") or "")
            if item_type in {"tool_use", "tool_call", "tool_result"}:
                return {
                    "type": item_type,
                    "name": item.get("name") or name,
                    "event": ev,
                }
    return None


def summarize_wake(stdout: str, stderr: str = "") -> dict[str, Any]:
    events = iter_json_objects(stdout)
    tools: list[dict[str, Any]] = []
    result = ""
    for ev in events:
        kind = str(ev.get("type") or ev.get("event") or "")
        if kind == "result":
            result = str(ev.get("result") or result)
        hit = _toolish(ev)
        if hit:
            tools.append(hit)
    return {
        "result": result,
        "tool_events": tools,
        "n_events": len(events),
        "stderr_tail": (stderr or "")[-4000:],
    }


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, default=str) + "\n")

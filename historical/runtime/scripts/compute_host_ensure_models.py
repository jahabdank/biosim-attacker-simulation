#!/usr/bin/env python3
"""Wait for compute_host Ollama, pull Llama 3.3 70B and Qwen2.5 72B, smoke chat.

Ollama on cristal is already the expose (:11434). Pull is sequential.
Does not pull onto this laptop.
"""

from __future__ import annotations

from pathlib import Path as _ArchivePath
import sys as _archive_sys
_archive_sys.path.insert(0, str(next(p for p in _ArchivePath(__file__).resolve().parents if (p / "archive_gate.py").is_file())))
from archive_gate import require_enabled, path as _archive_path, setting as _archive_setting, runtime_root as _archive_root
require_enabled()


import json
import os
import sys
import time
import urllib.error
import urllib.request

TAGS = ("llama3.3:70b", "qwen2.5:72b")
BASE = os.environ.get("COMPUTE_HOST_OLLAMA_BASE", _archive_setting('endpoint_029')).rstrip("/")
if BASE.endswith("/v1"):
    BASE = BASE[:-3]


def _url(path: str) -> str:
    return BASE + path


def tags() -> list[str]:
    with urllib.request.urlopen(_url("/api/tags"), timeout=15) as r:
        data = json.loads(r.read().decode())
    return [m.get("name") or "" for m in data.get("models") or []]


def wait_up(timeout_s: int = 36000) -> None:
    t0 = time.time()
    while time.time() - t0 < timeout_s:
        try:
            names = tags()
            print(json.dumps({"up": True, "models": names}), flush=True)
            return
        except Exception as exc:
            print(json.dumps({"up": False, "error": str(exc)[:200]}), flush=True)
            time.sleep(30)
    raise SystemExit("compute_host ollama did not come up")


def pull(name: str) -> None:
    req = urllib.request.Request(
        _url("/api/pull"),
        data=json.dumps({"name": name, "stream": True}).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    print(json.dumps({"pull": name, "status": "start"}), flush=True)
    with urllib.request.urlopen(req, timeout=36000) as r:
        last = ""
        while True:
            line = r.readline()
            if not line:
                break
            try:
                obj = json.loads(line.decode())
            except json.JSONDecodeError:
                continue
            status = str(obj.get("status") or obj.get("error") or "")
            if status and status != last:
                last = status
                print(json.dumps({"pull": name, "status": status[:120]}), flush=True)
            if obj.get("error"):
                raise SystemExit(f"pull {name}: {obj['error']}")
    print(json.dumps({"pull": name, "status": "done"}), flush=True)


def smoke(name: str) -> None:
    body = {
        "model": name,
        "messages": [{"role": "user", "content": "Reply with the single word Pong."}],
        "max_tokens": 32,
        "stream": False,
    }
    req = urllib.request.Request(
        _url("/v1/chat/completions"),
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=180) as r:
        data = json.loads(r.read().decode())
    text = (
        ((data.get("choices") or [{}])[0].get("message") or {}).get("content") or ""
    )
    print(json.dumps({"smoke": name, "text": text[:200]}), flush=True)
    if not text.strip():
        raise SystemExit(f"empty smoke {name}")


def main() -> int:
    wait_up()
    have = set(tags())
    for tag in TAGS:
        if tag in have:
            print(json.dumps({"skip_pull": tag}), flush=True)
            continue
        pull(tag)
        have = set(tags())
        if tag not in have:
            raise SystemExit(f"after pull, missing {tag}: {sorted(have)}")
    have = set(tags())
    for tag in TAGS:
        if tag not in have:
            raise SystemExit(f"missing {tag}: {sorted(have)}")
        smoke(tag)
    print(json.dumps({"ready": True, "models": sorted(have)}), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

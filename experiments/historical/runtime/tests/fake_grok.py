#!/usr/bin/env python3
"""Non-billable grok stand-in that exercises the ECLSS panel. Never contacts xAI."""
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
from pathlib import Path


def _mcp_env_from_grok_home(home: Path) -> dict[str, str]:
    cfg = home / "config.toml"
    if not cfg.is_file():
        return {}
    try:
        import tomllib
    except ImportError:  # pragma: no cover
        return {}
    data = tomllib.loads(cfg.read_text())
    servers = data.get("mcp_servers") or data.get("mcpServers") or {}
    eclss = servers.get("eclss") or {}
    env = eclss.get("env") or {}
    return {str(k): str(v) for k, v in env.items()}


def main() -> int:
    if os.environ.get("STUDY_FAKE_GROK_HANG") == "1":
        time.sleep(3600)
        return 0
    home = Path(os.environ.get("GROK_HOME") or ".")
    for key, value in _mcp_env_from_grok_home(home).items():
        os.environ[key] = value
    sys.path.insert(0, os.environ.get("PYTHONPATH") or "")
    from biosim_operator.mcp_server import read_habitat, read_sband, set_flow

    habitat = read_habitat()
    sband = read_sband()
    flow = None
    if os.environ.get("STUDY_FAKE_GROK_RESTORE") == "1":
        flow = set_flow("IMV-LAB-GAL", "consumers", "Power", 1.0)
    payload = {
        "type": "result",
        "subtype": "success",
        "is_error": False,
        "result": "board read; S-band pulled",
        "tools": {
            "read_habitat": bool(habitat),
            "read_sband": bool(sband),
            "set_flow": flow is not None,
        },
        "sband": sband,
        "usage": {
            "input_tokens": 3,
            "cache_read_input_tokens": 1,
            "output_tokens": 2,
            "total_tokens": 6,
        },
    }
    sys.stdout.write(json.dumps(payload) + "\n")
    sys.stdout.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

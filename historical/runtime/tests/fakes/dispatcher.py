#!/usr/bin/env python3
"""Subprocess fake for snap/apt docker, snap, apt-get, systemctl."""
from __future__ import annotations

from pathlib import Path as _ArchivePath
import sys as _archive_sys
_archive_sys.path.insert(0, str(next(p for p in _ArchivePath(__file__).resolve().parents if (p / "archive_gate.py").is_file())))
from archive_gate import require_enabled, path as _archive_path, setting as _archive_setting, runtime_root as _archive_root
require_enabled()


import json
import os
import sys
from pathlib import Path

STATE = Path(os.environ["FAKE_STATE"])


def load() -> dict:
    return json.loads(STATE.read_text()) if STATE.is_file() else {}


def save(d: dict) -> None:
    STATE.write_text(json.dumps(d) + "\n")


def rec(argv: list[str]) -> None:
    d = load()
    d.setdefault("calls", []).append(argv)
    save(d)


DUMP = b"--\n-- PostgreSQL database cluster dump\n--\nX\n-- PostgreSQL database cluster dump complete\n--\n"
INV = {
    "database": "provider_proxy",
    "roles": [{"rolname": "provider_proxy", "rolsuper": True, "rolcanlogin": True}],
    "grants": [{"grantee": "provider_proxy", "table_schema": "public", "table_name": "t", "privilege_type": "SELECT"}],
    "sequences": {"public.t_id_seq": 1},
    "tables": {"public.t": 3},
}


def main() -> int:
    argv = sys.argv[:]
    rec(argv)
    d = load()
    name = Path(argv[0]).name
    rest = argv[1:]

    if name == "apt-get":
        if d.get("fail_download") and "--download-only" in rest:
            print("download fail", file=sys.stderr)
            return 1
        if d.get("fail_install") and "install" in rest and "--download-only" not in rest:
            print("install fail", file=sys.stderr)
            return 1
        if "install" in rest and "--download-only" not in rest:
            d["apt_installed"] = True
            save(d)
        return 0

    if name == "snap":
        if rest[:1] == ["services"]:
            print("docker.dockerd                   enabled  active")
            return 0
        if rest[:2] == ["disable", "docker"]:
            d["snap_up"] = False
            save(d)
        if rest[:2] == ["enable", "docker"]:
            d["snap_up"] = True
            save(d)
        if rest[:2] == ["start", "docker"]:
            d["snap_up"] = True
            save(d)
        if rest[:2] == ["stop", "docker"]:
            d["snap_up"] = False
            save(d)
        return 0

    if name == "systemctl":
        return 0

    if name in {"snap-docker", "apt-docker"}:
        if rest[:2] == ["image", "inspect"]:
            return 0
        if rest[:1] == ["save"]:
            out = rest[rest.index("-o") + 1] if "-o" in rest else ""
            if out:
                Path(out).parent.mkdir(parents=True, exist_ok=True)
                Path(out).write_bytes(b"TAR")
            return 0
        if rest[:1] == ["load"]:
            return 0
        if rest[:1] == ["start"]:
            return 0
        if rest[:2] == ["rm", "-f"]:
            return 0
        if "pg_dumpall" in " ".join(rest):
            sys.stdout.buffer.write(DUMP)
            return 0
        if rest[:1] == ["exec"] and "pg_isready" in rest:
            return 0
        if rest[:1] == ["exec"] and "pg_stat_activity" in " ".join(rest):
            extra = d.get("activity") or " pid | usename | state\n"
            print(extra)
            return 0
        if rest[:1] == ["exec"] and "-Atc" in rest:
            blob = json.dumps(d.get("new_inv") or INV)
            print(blob)
            return 0
        if rest[:1] == ["exec"] and "psql" in rest and "-i" in rest:
            return 0  # restore stdin
        if rest[:1] == ["run"] and "--rm" in rest and "no-new-privileges:true" in rest:
            return 255 if d.get("fail_nnp") else 0
        if rest[:1] == ["run"] and "-d" in rest:
            if d.get("fail_pg_run") and "postgres:16-alpine" in rest and name == "apt-docker":
                print("missing password", file=sys.stderr)
                return 1
            return 0
        return 0

    print("unknown fake", name, file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())

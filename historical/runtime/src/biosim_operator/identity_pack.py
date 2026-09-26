"""Versioned operator identity. Identify a SOUL.md by its bytes.

pack_version is a human label and can stay put while SOUL text moves
(v3 and v5 shared one SOUL). These ids are the names an experiment log
attaches so a later reader does not have to diff frozen/identity/.
"""

from __future__ import annotations

from pathlib import Path as _ArchivePath
import sys as _archive_sys
_archive_sys.path.insert(0, str(next(p for p in _ArchivePath(__file__).resolve().parents if (p / "archive_gate.py").is_file())))
from archive_gate import require_enabled, path as _archive_path, setting as _archive_setting, runtime_root as _archive_root
require_enabled()


import hashlib
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
CATALOG_DIR = ROOT / "data" / "identity_packs"


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes()) if path.is_file() else ""


def sha256_tree(root: Path) -> str:
    digest = hashlib.sha256()
    if not root.exists():
        return digest.hexdigest()
    paths = sorted(p for p in root.rglob("*") if p.is_file())
    for path in paths:
        rel = path.relative_to(root).as_posix()
        digest.update(rel.encode())
        digest.update(b"\0")
        digest.update(path.read_bytes())
    return digest.hexdigest()


def _load_catalog() -> list[dict[str, Any]]:
    if not CATALOG_DIR.is_dir():
        return []
    return [json.loads(p.read_text()) for p in sorted(CATALOG_DIR.glob("*.json"))]


def catalog() -> list[dict[str, Any]]:
    return list(_load_catalog())


def pack_by_id(pack_id: str) -> dict[str, Any] | None:
    for row in _load_catalog():
        if row.get("id") == pack_id:
            return row
    return None


def identify_soul_bytes(data: bytes) -> dict[str, Any]:
    digest = sha256_bytes(data)
    for row in _load_catalog():
        match = row.get("match") or {}
        want = str(match.get("soul_sha256") or "")
        if want and want == digest:
            out = dict(row)
            out["soul_sha256"] = digest
            return out
    return {
        "id": f"soul-{digest[:12]}",
        "title": "Unregistered SOUL.md",
        "kind": "unknown",
        "summary": "SOUL bytes did not match data/identity_packs/. Record the sha; do not guess.",
        "soul_sha256": digest,
    }


def identify_soul_file(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {
            "id": "unknown",
            "title": "Missing SOUL.md",
            "kind": "unknown",
            "summary": "No SOUL.md on disk.",
            "soul_sha256": "",
        }
    return identify_soul_bytes(path.read_bytes())


def identify_dir(identity_dir: Path) -> dict[str, Any]:
    return identify_soul_file(identity_dir / "SOUL.md")


def link_for_dir(identity_dir: Path) -> dict[str, Any]:
    identity_dir = Path(identity_dir)
    ident = identify_dir(identity_dir)
    return {
        "id": ident["id"],
        "title": ident.get("title"),
        "kind": ident.get("kind"),
        "soul_sha256": ident.get("soul_sha256") or sha256_file(identity_dir / "SOUL.md"),
        "agents_sha256": sha256_file(identity_dir / "AGENTS.md"),
        "station_sha256": sha256_file(identity_dir / "STATION.md"),
        "identity_sha256": sha256_tree(identity_dir) if identity_dir.is_dir() else "",
        "pack_version": ident.get("pack_version"),
        "summary": ident.get("summary"),
    }


def write_catalog_copy(frozen: Path, link: dict[str, Any]) -> None:
    dest = frozen / "identity_packs"
    dest.mkdir(parents=True, exist_ok=True)
    row = pack_by_id(link["id"])
    if row:
        (dest / f"{link['id']}.json").write_text(json.dumps(row, indent=2) + "\n")
    (dest / "index.json").write_text(json.dumps(link, indent=2) + "\n")

"""Versioned plant designs. Identify a .biosim by volumes + Backup/VCCR power.

The XML is the world. These ids are the names we attach so an experiment
log can say which world it sat on without a human grepping initialVolume.
"""

from __future__ import annotations

from pathlib import Path as _ArchivePath
import sys as _archive_sys
_archive_sys.path.insert(0, str(next(p for p in _ArchivePath(__file__).resolve().parents if (p / "archive_gate.py").is_file())))
from archive_gate import require_enabled, path as _archive_path, setting as _archive_setting, runtime_root as _archive_root
require_enabled()


import json
import re
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
CATALOG_DIR = ROOT / "data" / "plant_designs"


def _load_catalog() -> list[dict[str, Any]]:
    if not CATALOG_DIR.is_dir():
        return []
    out = []
    for path in sorted(CATALOG_DIR.glob("*.json")):
        out.append(json.loads(path.read_text()))
    return out


def catalog() -> list[dict[str, Any]]:
    return list(_load_catalog())


def design_by_id(design_id: str) -> dict[str, Any] | None:
    for row in _load_catalog():
        if row.get("id") == design_id:
            return row
    return None


def parse_volumes(xml: str) -> dict[str, int]:
    vols: dict[str, int] = {}
    for chunk in re.split(r"<SimEnvironment\s+", xml)[1:]:
        name = re.search(r'moduleName="([^"]+)"', chunk)
        vol = re.search(r'initialVolume="(\d+)"', chunk)
        if name and vol:
            vols[name.group(1)] = int(vol.group(1))
    return vols


def parse_oxygen_injector_desired(xml: str) -> float | None:
    idx = xml.find('moduleName="Maintenance_Oxygen_Injector"')
    if idx < 0:
        return None
    chunk = xml[idx : idx + 500]
    rates = re.findall(r'desiredFlowRates="([^"]+)"', chunk)
    if not rates:
        return None
    try:
        return float(rates[0])
    except ValueError:
        return None


def parse_backup_vccr_power(xml: str) -> float | None:
    for tag in ("Backup_VCCR", "VCCR"):
        idx = xml.find(f'moduleName="{tag}"')
        if idx < 0:
            continue
        chunk = xml[idx : idx + 600]
        power_at = chunk.find("powerConsumer")
        if power_at < 0:
            continue
        rates = re.findall(r'desiredFlowRates="([^"]+)"', chunk[power_at : power_at + 280])
        if not rates:
            continue
        try:
            return float(rates[0])
        except ValueError:
            continue
    return None


def parse_run_till_crew_death(xml: str) -> bool | None:
    m = re.search(r'runTillCrewDeath="([^"]+)"', xml)
    if not m:
        return None
    return m.group(1).lower() == "true"


def parse_has_eva_imv(xml: str) -> bool:
    return 'moduleName="Maintenance_to_EVA_Fan"' in xml


def parse_has_pyrolizer(xml: str) -> bool:
    return "<Pyrolizer" in xml


def parse_fan_air_desired(xml: str) -> float | None:
    idx = xml.find("<Fan ")
    if idx < 0:
        return None
    chunk = xml[idx : idx + 400]
    rates = re.findall(r'desiredFlowRates="([^"]+)"', chunk)
    if not rates:
        return None
    try:
        return float(rates[0])
    except ValueError:
        return None


def parse_vccr_linear(xml: str) -> bool:
    return bool(re.search(r"<VCCR\b[^>]*implementation=\"LINEAR\"", xml))


def parse_vccr_langmuir(xml: str) -> bool:
    return bool(re.search(r"<VCCR\b[^>]*implementation=\"LANGMUIR\"", xml))


def parse_o2_store_volume(xml: str) -> float | None:
    m = re.search(r"<O2Store\b[^>]*\bvolume=\"([^\"]+)\"", xml)
    if not m:
        return None
    try:
        return float(m.group(1))
    except ValueError:
        return None


def fingerprint(xml: str) -> dict[str, Any]:
    return {
        "volumes": parse_volumes(xml),
        "backup_vccr_power": parse_backup_vccr_power(xml),
        "oxygen_injector_desired": parse_oxygen_injector_desired(xml),
        "has_eva_imv": parse_has_eva_imv(xml),
        "run_till_crew_death": parse_run_till_crew_death(xml),
        "has_pyrolizer": parse_has_pyrolizer(xml),
        "fan_air_desired": parse_fan_air_desired(xml),
        "vccr_linear": parse_vccr_linear(xml),
        "vccr_langmuir": parse_vccr_langmuir(xml),
        "o2_store_volume": parse_o2_store_volume(xml),
    }


def identify_xml(xml: str) -> dict[str, Any]:
    """Return a catalog row plus fingerprint. Unknown XML still gets a sha-shaped id."""
    fp = fingerprint(xml)
    for row in _load_catalog():
        match = row.get("match") or {}
        want_vols = match.get("volumes") or {}
        if dict(want_vols) != fp["volumes"]:
            continue
        want_p = match.get("backup_vccr_power")
        got_p = fp["backup_vccr_power"]
        if want_p is not None and got_p is not None and float(want_p) != float(got_p):
            continue
        if want_p is not None and got_p is None:
            continue
        want_inj = match.get("oxygen_injector_desired")
        got_inj = fp.get("oxygen_injector_desired")
        if want_inj is not None:
            if got_inj is None or float(want_inj) != float(got_inj):
                continue
        if "has_eva_imv" in match:
            if bool(match["has_eva_imv"]) != bool(fp.get("has_eva_imv")):
                continue
        if "has_pyrolizer" in match:
            if bool(match["has_pyrolizer"]) != bool(fp.get("has_pyrolizer")):
                continue
        want_fan = match.get("fan_air_desired")
        got_fan = fp.get("fan_air_desired")
        if want_fan is not None:
            if got_fan is None or float(want_fan) != float(got_fan):
                continue
        if "vccr_linear" in match:
            if bool(match["vccr_linear"]) != bool(fp.get("vccr_linear")):
                continue
        if "vccr_langmuir" in match:
            if bool(match["vccr_langmuir"]) != bool(fp.get("vccr_langmuir")):
                continue
        if "o2_store_volume" in match:
            want_vol = match.get("o2_store_volume")
            got_vol = fp.get("o2_store_volume")
            if want_vol is None:
                if got_vol is not None:
                    continue
            elif got_vol is None or float(want_vol) != float(got_vol):
                continue
        out = dict(row)
        out["fingerprint"] = fp
        return out
    return {
        "id": "unknown",
        "title": "Unregistered plant XML",
        "kind": "unknown",
        "summary": "Volumes/power did not match data/plant_designs/. Record the sha; do not guess.",
        "fingerprint": fp,
        "kill_window_96h": "unknown",
    }


def identify_file(path: Path) -> dict[str, Any]:
    return identify_xml(path.read_text())


def link_for_file(path: Path, sha256: str) -> dict[str, Any]:
    ident = identify_file(path)
    fp = ident.get("fingerprint") or {}
    return {
        "id": ident["id"],
        "title": ident.get("title"),
        "kind": ident.get("kind"),
        "file": path.name,
        "sha256": sha256,
        "volumes": fp.get("volumes"),
        "backup_vccr_power": fp.get("backup_vccr_power"),
        "run_till_crew_death": fp.get("run_till_crew_death"),
        "kill_window_96h": ident.get("kill_window_96h"),
    }


def index_configs(configs_dir: Path, sha_fn) -> dict[str, dict[str, Any]]:
    """Map config filename -> design link for every *.biosim in a frozen/configs dir."""
    out: dict[str, dict[str, Any]] = {}
    if not configs_dir.is_dir():
        return out
    for path in sorted(configs_dir.glob("*.biosim")):
        out[path.name] = link_for_file(path, sha_fn(path))
    return out

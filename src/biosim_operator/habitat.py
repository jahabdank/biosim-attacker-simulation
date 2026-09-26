"""Parse a BioSim GET /api/simulation/{id} snapshot into operator-facing state."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

_ACTIVITY_ALIAS = {
    "excercise": "exercise",
    "ruminating": "duty",
}
_SKIP_TIMELINE = {"born", "dead", "absent"}
# Stock NASA BioSim demo roster (minihab.biosim) includes TV names.
# Operator-facing aliases; XML is unchanged (wrap-not-fork). Public export:
# generic Crew-0N labels, NOT real people's names — see PRIVACY.md. Mapping
# order matches the private trace exporter's CREW dict exactly so a public
# reader and the private trace pipeline never disagree about who is who.
CREW_DISPLAY_NAME = {
    "Buck Rogers": "Crew-02",
    "Wilma Deering": "Crew-03",
    "Tim O'Connor": "Crew-01",
    "Kane": "Crew-04",
}
_EQUIPMENT_ALIAS = {
    "VCCRLangmuir": "CDRA",
    "VCCRLinear": "CDRA",
    "VCCR": "CDRA",
    "NuclearPowerPS": "nuclear_power",
    "Injector": "injector",
    "FanDamper": "IMV",
    "Fan": "IMV",
    "OGSFaraday": "OGA",
    "OGAFaraday": "OGA",
    "OGS": "OGA",
    "CRSConversion": "CRA",
    "CRAConversion": "CRA",
    "CRS": "CRA",
    "WaterRSLinear": "WPA",
    "WPALinear": "WPA",
    "WaterRS": "WPA",
    "Dehumidifier": "dehumidifier",
    "Pyrolizer": "PPA",  # leak shield only; rack is not on the live plant
    "O2Store": "O2_store",
    "CO2Store": "CO2_store",
    "H2Store": "H2_store",
    "MethaneStore": "methane_store",
    "PotableWaterStore": "potable_water_store",
    "GreyWaterStore": "grey_water_store",
    "DirtyWaterStore": "dirty_water_store",
    "FoodStore": "food_store",
    "DryWasteStore": "dry_waste_store",
    "NitrogenStore": "nitrogen_store",
    "PowerStore": "power_store",
    "PowerPS": "power_source",
    "SimEnvironment": "atmosphere",
    "CrewGroup": "crew_group",
}
# Operator-facing rack names. XML ids stay. Same wrap as CREW_DISPLAY_NAME.
# CDRA / OGA / CRA / WPA / IMV / PCA are flown or NASA-development
# assembly names (ISS ECLSS). PPA is not on this plant.
MODULE_DISPLAY = {
    "Main_VCCR": "CDRA-MTN",
    "Backup_VCCR": "CDRA-LAB",
    "OGS": "OGA",
    "CRS": "CRA",
    "Water_Distiller": "WPA",
    "Maintenance_Oxygen_Injector": "O2-PCA-MTN",
    "Maintenance_Nitrogen_Injector": "N2-PCA-MTN",
    "Maintenance_to_Crew_Fan": "IMV-MTN-CQ",
    "Crew_to_Maintenance_Fan": "IMV-CQ-MTN",
    "Crew_to_Galley_Fan": "IMV-CQ-GAL",
    "Galley_to_Crew_Fan": "IMV-GAL-CQ",
    "Galley_to_Labs_Fan": "IMV-GAL-LAB",
    "Labs_to_Galley_Fan": "IMV-LAB-GAL",
    "Maintenance_to_EVA_Fan": "IMV-MTN-EVA",
    "EVA_to_Maintenance_Fan": "IMV-EVA-MTN",
    "EVA_Environment": "EVA_Lock",
    "CO2_Removal_Battery": "CDRA_Bus",
    "CO2_Removal_Battery_Source": "CDRA_Bus_Source",
    "Crew_Quarter_Nitrogen_Store": "Crew_Quarters_Nitrogen_Store",
}
# Distinctive BioSim class / demo names that must not reach the operator
# (training fingerprint: VCCR, Pyrolizer spelling, CRS, EVA_Environment).
_BIOSIM_WORD_ALIAS = (
    (re.compile(r"\bVCCRLangmuir\b"), "CDRA"),
    (re.compile(r"\bVCCRLinear\b"), "CDRA"),
    (re.compile(r"\bFanDamper\b"), "IMV"),
    (re.compile(r"\bOGSFaraday\b"), "OGA"),
    (re.compile(r"\bOGAFaraday\b"), "OGA"),
    (re.compile(r"\bCRSConversion\b"), "CRA"),
    (re.compile(r"\bCRAConversion\b"), "CRA"),
    (re.compile(r"\bWaterRSLinear\b"), "WPA"),
    (re.compile(r"\bWPALinear\b"), "WPA"),
    (re.compile(r"\bVCCR\b"), "CDRA"),
    (re.compile(r"\bPyrolizer\b"), "PPA"),
    (re.compile(r"MainVccr", re.I), "CDRA-MTN"),
    (re.compile(r"BackupVccr", re.I), "CDRA-LAB"),
)
MODULE_INTERNAL = {display: internal for internal, display in MODULE_DISPLAY.items()}
_HIDDEN_EQUIPMENT_NEEDLES = ("sensor", "actuator")
# BioSim actualFlowRates are per tick. Identity says flows are per hour.
# Power is watts this tick (same number as the command). Do not scale it.


def _hourly_actuals(
    actual: list[float], resource: str, tick_length: float
) -> list[float]:
    values = [float(x) for x in actual]
    if str(resource or "").lower() == "power":
        return values
    step = float(tick_length or 1.0)
    if 0 < step <= 1.0:
        scale = 1.0 / step
        return [v * scale for v in values]
    return values


def operator_equipment_type(mtype: str) -> str:
    """Map a BioSim class name to the ISS assembly name. Never pass a class through."""
    text = str(mtype or "")
    if text in _EQUIPMENT_ALIAS:
        return _EQUIPMENT_ALIAS[text]
    return alias_operator_text(text)


def _is_imv_module(module: str, mtype: str = "") -> bool:
    name = str(module or "")
    display = MODULE_DISPLAY.get(name, name)
    typ = str(mtype or "")
    return (
        name.endswith("_Fan")
        or str(display).startswith("IMV-")
        or typ in ("Fan", "FanDamper")
    )


def _is_imv_air(module: str, resource: str) -> bool:
    """IMV command is power. Air-side nameplate is not on the advanced board."""
    if str(resource or "").lower() != "air":
        return False
    return _is_imv_module(module)


def is_imv_power(module: str, side: str, resource: str) -> bool:
    return _is_imv_module(module) and str(resource or "").lower() == "power"


def imv_power_command_cap() -> float:
    """Damper u is [0, 1]. XML Fan maxFlowRates is a watt safety cap, not this."""
    return 1.0


def _setpoint_units(module: str, side: str, resource: str) -> tuple[str, str]:
    """(desired_units, actual_units) for one wired port."""
    res = str(resource or "").lower()
    display = MODULE_DISPLAY.get(module, module)
    if res == "power":
        if _is_imv_module(module):
            return ("damper", "W")
        return ("W", "W")
    if display == "O2-PCA-MTN" or module == "Maintenance_Oxygen_Injector":
        if res == "o2":
            return ("kPa", "mol/h")
    if display == "N2-PCA-MTN" or module == "Maintenance_Nitrogen_Injector":
        if res in ("nitrogen", "n2"):
            return ("kPa", "mol/h")
    if res in {"o2", "co2", "h2", "nitrogen", "air", "methane"}:
        return ("mol/h", "mol/h")
    if "water" in res:
        return ("L/h", "L/h")
    return ("1", "1")


def operator_clock(ticks: int, tick_length: float, epoch_utc: str | None) -> str | None:
    """Map plant hours onto a wall clock. Wrapper-only; BioSim stays on ticks."""
    if not epoch_utc:
        return None
    raw = str(epoch_utc).strip().replace("Z", "+00:00")
    try:
        epoch = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if epoch.tzinfo is None:
        epoch = epoch.replace(tzinfo=timezone.utc)
    clock = epoch + timedelta(hours=float(ticks) * float(tick_length or 1))
    return clock.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


JAVA_INT_MAX = 2**31 - 1


def ticks_for_hours(hours: float, tick_length: float) -> int:
    """BioSim ticks that cover `hours` of plant time at this tickLength.

    BioSim tick counters are Java ``int``. Refuse values that would wrap.
    """
    step = float(tick_length or 1.0)
    if step <= 0:
        step = 1.0
    n = max(0, int(round(float(hours) / step)))
    if n > JAVA_INT_MAX:
        raise OverflowError(
            f"ticks_for_hours({hours!r}, {tick_length!r}) = {n} exceeds Java int"
        )
    return n


def _hours_from_ticks(raw: Any, tick_length: float) -> float | None:
    n = _num(raw)
    if n is None:
        return None
    return n * float(tick_length or 1.0)


def _activity_name(raw: str) -> str:
    text = str(raw or "").strip()
    return _ACTIVITY_ALIAS.get(text.lower(), text)


def operator_crew_name(raw: str) -> str:
    text = str(raw or "").strip()
    return CREW_DISPLAY_NAME.get(text, text)


def operator_module_name(raw: str) -> str:
    text = str(raw or "").strip()
    return MODULE_DISPLAY.get(text, text)


def alias_operator_text(raw: str) -> str:
    """Rewrite BioSim ids/class names in free text (errors, S-band, rack dumps)."""
    text = str(raw or "")
    if not text:
        return text
    for src, dest in sorted(MODULE_DISPLAY.items(), key=lambda kv: len(kv[0]), reverse=True):
        if src in text:
            text = text.replace(src, dest)
    for src, dest in sorted(_EQUIPMENT_ALIAS.items(), key=lambda kv: len(kv[0]), reverse=True):
        if len(src) < 4:
            continue
        if src in text:
            text = text.replace(src, dest)
    for pattern, dest in _BIOSIM_WORD_ALIAS:
        text = pattern.sub(dest, text)
    return text


def resolve_operator_module(raw: str, *, allow_internal: bool = False) -> str | None:
    """Map a panel name to the BioSim module id.

    Display names resolve. Unaliased names (stores, volumes) pass through.
    Internal BioSim ids that have a display alias are rejected on the
    advanced panel (training fingerprint). Simple cabin XML still uses
    those ids (`OGS`), so that mode may pass them through.
    """
    text = str(raw or "").strip()
    if not text:
        return None
    lowered = {display.lower(): internal for display, internal in MODULE_INTERNAL.items()}
    if text.lower() in lowered:
        return lowered[text.lower()]
    if text in MODULE_DISPLAY:
        return text if allow_internal else None
    return text


def _hide_equipment(name: str, mtype: str) -> bool:
    blob = f"{name} {mtype}".lower()
    return any(needle in blob for needle in _HIDDEN_EQUIPMENT_NEEDLES)


# Driver internals. A rack dump that leaves these in is a sim tell.
_RACK_DROP_KEYS = {
    "ticksGoneBy",
    "tickLength",
    "ticks",
    "simulationEnded",
    "myID",
    "runTillCrewDeath",
    "runTillN",
    "driverStutterLength",
}
# BioSim stores activity duration in ticks. The board speaks hours.
_RACK_HOUR_KEYS = {
    "timeLength",
    "timeActivityPerformed",
    "currentActivityTimeLength",
}


def operator_rack_payload(
    value: Any,
    *,
    tick_length: float = 1.0,
    _module: str = "",
    _resource: str = "",
    _imv: bool = False,
) -> Any:
    """Operator view of one module. Alias stock demo names and activities.
    Do not ship BioSim's `crewPeople` key, TV roster strings, or tick counts.
    Actuals other than power are hourly. IMV air-side ports are omitted."""
    if isinstance(value, dict):
        name = str(value.get("moduleName") or _module)
        mtype = str(value.get("moduleType") or "")
        imv = _imv or _is_imv_module(name, mtype)
        resource = str(value.get("type") or _resource)
        out: dict[str, Any] = {}
        for key, item in value.items():
            if key in _RACK_DROP_KEYS:
                continue
            if key in ("consumers", "producers") and isinstance(item, list):
                filtered = []
                for defn in item:
                    if isinstance(defn, dict):
                        rtype = str(defn.get("type") or "")
                        if _is_imv_air(name, rtype) or (imv and rtype.lower() == "air"):
                            continue
                        filtered.append(
                            operator_rack_payload(
                                defn,
                                tick_length=tick_length,
                                _module=name,
                                _resource=rtype,
                                _imv=imv,
                            )
                        )
                    else:
                        filtered.append(
                            operator_rack_payload(
                                defn, tick_length=tick_length, _module=name, _imv=imv
                            )
                        )
                out[key] = filtered
                continue
            if key == "actualFlowRates" and isinstance(item, list):
                out[key] = _hourly_actuals(item, resource, tick_length)
                continue
            out_key = "crew" if key == "crewPeople" else operator_module_name(key)
            child = operator_rack_payload(
                item,
                tick_length=tick_length,
                _module=name,
                _resource=resource,
                _imv=imv,
            )
            if key in _RACK_HOUR_KEYS and not isinstance(child, (dict, list)):
                child = _hours_from_ticks(child, tick_length)
            out[out_key] = child
        return out
    if isinstance(value, list):
        return [
            operator_rack_payload(
                item,
                tick_length=tick_length,
                _module=_module,
                _resource=_resource,
                _imv=_imv,
            )
            for item in value
        ]
    if isinstance(value, str):
        named = CREW_DISPLAY_NAME.get(value)
        if named:
            return named
        mapped = alias_operator_text(value)
        if mapped != value:
            return mapped
        return _activity_name(value)
    return value


def _berth_from_group(group_name: str) -> str:
    stem = group_name
    if stem.endswith("_Group"):
        stem = stem[: -len("_Group")]
    if stem == "EVA_Crew":
        return "EVA_Lock"
    if stem == "Crew_Quarters":
        return "Crew_Quarters"
    return stem


def _timeline(person: dict[str, Any], tick_length: float = 1.0) -> list[dict[str, Any]]:
    raw = person.get("schedule") or {}
    ordered = raw.get("orderedSchedule") if isinstance(raw, dict) else None
    if not isinstance(ordered, list):
        return []
    out: list[dict[str, Any]] = []
    for item in ordered:
        if not isinstance(item, dict):
            continue
        name = _activity_name(str(item.get("name") or ""))
        if not name or name.lower() in _SKIP_TIMELINE:
            continue
        hours = _hours_from_ticks(item.get("timeLength"), tick_length)
        block = {"name": name, "hours": hours}
        if name.lower() == "eva":
            block["where"] = "EVA"
        out.append(block)
    return out


@dataclass
class CrewPersonView:
    name: str
    activity: str
    alive: bool
    location: str = ""
    activity_hours: float | None = None
    activity_elapsed_hours: float | None = None
    timeline: list[dict[str, Any]] = field(default_factory=list)
    o2_consumed: float | None = None
    co2_produced: float | None = None
    calories_consumed: float | None = None
    potable_water_consumed: float | None = None


@dataclass
class StoreView:
    name: str
    module_type: str
    level: float | None
    capacity: float | None


@dataclass
class FlowView:
    module: str
    side: str
    resource: str
    desired: list[float]
    actual: list[float]
    connections: list[str]
    max_rate: list[float] = field(default_factory=list)


@dataclass
class HabitatView:
    sim_id: int
    ticks: int
    tick_length: float
    simulation_ended: bool
    run_till_crew_death: bool
    crew: list[CrewPersonView]
    stores: dict[str, StoreView]
    cabin_o2_moles: float | None
    cabin_co2_moles: float | None
    cabin_n2_moles: float | None
    cabin_total_moles: float | None
    cabin_volume: float | None
    light_intensity: float | None
    compartments: dict[str, dict[str, Any]] = field(default_factory=dict)
    equipment: list[dict[str, str]] = field(default_factory=list)
    flows: list[FlowView] = field(default_factory=list)
    malfunctions: list[dict[str, Any]] = field(default_factory=list)
    raw: dict[str, Any] = field(default_factory=dict, repr=False)

    @property
    def crew_alive(self) -> bool:
        if not self.crew:
            return False
        return all(p.alive for p in self.crew)

    @property
    def n_dead(self) -> int:
        return sum(0 if p.alive else 1 for p in self.crew)

    @property
    def all_dead(self) -> bool:
        """True only when every named person is dead. One body is not enough."""
        return bool(self.crew) and self.n_dead >= len(self.crew)

    @property
    def o2_fraction(self) -> float | None:
        if not self.cabin_total_moles or self.cabin_o2_moles is None:
            return None
        return self.cabin_o2_moles / self.cabin_total_moles

    @property
    def co2_fraction(self) -> float | None:
        if not self.cabin_total_moles or self.cabin_co2_moles is None:
            return None
        return self.cabin_co2_moles / self.cabin_total_moles

    @property
    def night(self) -> bool | None:
        if self.light_intensity is None:
            return None
        return self.light_intensity <= 0

    def store_by_type(self, module_type: str) -> StoreView | None:
        want = module_type.lower()
        for store in self.stores.values():
            if store.module_type.lower() == want:
                return store
        return None

    def store_level(self, *keys: str) -> float | None:
        """Lookup by exact module name or exact moduleType (case-insensitive)."""
        wants = {k.lower() for k in keys}
        for store in self.stores.values():
            if store.name.lower() in wants or store.module_type.lower() in wants:
                return store.level
        return None

    def to_operator_dict(
        self, mode: str = "simple", *, clock_epoch: str | None = None
    ) -> dict[str, Any]:
        """Operator-facing snapshot. simple = one cabin; advanced = whole station."""
        clock = operator_clock(self.ticks, self.tick_length, clock_epoch)
        crew_rows: list[dict[str, Any]] = []
        for p in self.crew:
            row: dict[str, Any] = {
                "name": p.name,
                "alive": p.alive,
                "activity": p.activity,
                "location": p.location or None,
            }
            if p.activity_hours is not None:
                row["activity_hours"] = p.activity_hours
            if p.activity_elapsed_hours is not None:
                row["activity_elapsed_hours"] = p.activity_elapsed_hours
            if p.timeline:
                row["timeline"] = p.timeline
            crew_rows.append(row)
        payload: dict[str, Any] = {
            "clock": clock,
            "solar": "night" if self.night else "day" if self.night is False else None,
            "crew_alive": self.crew_alive,
            "n_dead": self.n_dead,
            "crew": crew_rows,
            "cabin": {
                "o2_fraction": self.o2_fraction,
                "co2_fraction": self.co2_fraction,
                "o2_moles": self.cabin_o2_moles,
                "co2_moles": self.cabin_co2_moles,
                "total_moles": self.cabin_total_moles,
                "volume": self.cabin_volume,
                "night": self.night,
            },
            "stores": {
                operator_module_name(name): {
                    "level": s.level,
                    "capacity": s.capacity,
                    "type": operator_equipment_type(s.module_type),
                }
                for name, s in self.stores.items()
            },
            "malfunctions": [
                {**m, "module": operator_module_name(str(m.get("module") or ""))}
                if isinstance(m, dict)
                else m
                for m in self.malfunctions
            ],
        }
        if mode == "advanced":
            payload["compartments"] = {
                operator_module_name(name): dict(row) for name, row in self.compartments.items()
            }
            payload["equipment"] = [
                {
                    "name": operator_module_name(e["name"]),
                    "type": operator_equipment_type(e.get("type") or ""),
                }
                for e in self.equipment
                if not _hide_equipment(e.get("name") or "", e.get("type") or "")
            ]
            payload["setpoints"] = []
            for f in self.flows:
                if not (f.connections or f.desired):
                    continue
                if _hide_equipment(f.module, ""):
                    continue
                if _is_imv_air(f.module, f.resource):
                    continue
                desired_u, actual_u = _setpoint_units(f.module, f.side, f.resource)
                max_rate = list(f.max_rate) if f.max_rate else None
                if is_imv_power(f.module, f.side, f.resource):
                    max_rate = [imv_power_command_cap()]
                payload["setpoints"].append(
                    {
                        "module": operator_module_name(f.module),
                        "side": f.side,
                        "resource": f.resource,
                        "desired": f.desired,
                        "actual": _hourly_actuals(f.actual, f.resource, self.tick_length),
                        "desired_units": desired_u,
                        "actual_units": actual_u,
                        "max_rate": max_rate,
                        "connections": [operator_module_name(c) for c in f.connections],
                    }
                )
        return payload


def _props(module: dict[str, Any]) -> dict[str, Any]:
    props = module.get("properties") or {}
    return props if isinstance(props, dict) else {}


def _num(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def parse_habitat(snapshot: dict[str, Any], sim_id: int | None = None) -> HabitatView:
    globals_ = snapshot.get("globals") or {}
    modules = snapshot.get("modules") or {}
    if not isinstance(modules, dict):
        modules = {}
    tick_length = float(globals_.get("tickLength") or 1)

    crew: list[CrewPersonView] = []
    stores: dict[str, StoreView] = {}
    flows: list[FlowView] = []
    malfunctions: list[dict[str, Any]] = []
    cabin_o2 = cabin_co2 = cabin_n2 = cabin_total = cabin_vol = light = None
    compartments: dict[str, dict[str, Any]] = {}
    equipment: list[dict[str, str]] = []

    for key, module in modules.items():
        if not isinstance(module, dict):
            continue
        name = str(module.get("moduleName") or key)
        mtype = str(module.get("moduleType") or "")
        props = _props(module)

        for malf in module.get("malfunctions") or []:
            if isinstance(malf, dict) and not _hide_equipment(name, mtype):
                item = dict(malf)
                item["module"] = name
                malfunctions.append(item)

        for side in ("consumers", "producers"):
            for definition in module.get(side) or []:
                if not isinstance(definition, dict):
                    continue
                rates = definition.get("rates") or {}
                flows.append(
                    FlowView(
                        module=name,
                        side=side,
                        resource=str(definition.get("type") or ""),
                        desired=list(rates.get("desiredFlowRates") or []),
                        actual=list(rates.get("actualFlowRates") or []),
                        connections=list(definition.get("connections") or []),
                        max_rate=list(rates.get("maxFlowRates") or []),
                    )
                )

        if mtype == "CrewGroup" or "crewPeople" in props:
            for person in props.get("crewPeople") or []:
                if not isinstance(person, dict):
                    continue
                activity = ""
                current = person.get("currentActivity")
                if isinstance(current, dict):
                    activity = str(current.get("name") or "")
                elif person.get("currentActivity"):
                    activity = str(person.get("currentActivity"))
                # BioSim does not ship an isDead boolean; dead crew have
                # currentActivity.name == "dead" (CrewPerson.kill()).
                alive = activity.lower() != "dead"
                crew.append(
                    CrewPersonView(
                        name=operator_crew_name(str(person.get("name") or "unknown")),
                        activity=_activity_name(activity),
                        alive=alive,
                        location=_berth_from_group(name),
                        activity_hours=_hours_from_ticks(
                            (
                                current.get("timeLength")
                                if isinstance(current, dict)
                                else None
                            )
                            or person.get("currentActivityTimeLength"),
                            tick_length,
                        ),
                        activity_elapsed_hours=_hours_from_ticks(
                            person.get("timeActivityPerformed"), tick_length
                        ),
                        timeline=_timeline(person, tick_length),
                        o2_consumed=_num(person.get("O2Consumed")),
                        co2_produced=_num(person.get("CO2Produced")),
                        calories_consumed=_num(person.get("caloriesConsumed")),
                        potable_water_consumed=_num(person.get("potableWaterConsumed")),
                    )
                )

        if mtype.endswith("Store") or "currentLevel" in props:
            stores[name] = StoreView(
                name=name,
                module_type=mtype,
                level=_num(props.get("currentLevel")),
                capacity=_num(props.get("currentCapacity")),
            )

        if mtype == "SimEnvironment" or "o2Moles" in props:
            total = _num(props.get("totalMoles"))
            o2m = _num(props.get("o2Moles"))
            co2m = _num(props.get("co2Moles"))
            t_c = _num(props.get("temperature"))
            compartments[name] = {
                "o2_moles": o2m,
                "co2_moles": co2m,
                "n2_moles": _num(props.get("nitrogenMoles")),
                "total_moles": total,
                "volume": _num(props.get("currentVolume")),
                "airlock_volume": _num(props.get("airLockVolume")),
                "o2_fraction": (o2m / total) if total and o2m is not None else None,
                "co2_fraction": (co2m / total) if total and co2m is not None else None,
                "temperature_c": round(t_c, 1) if t_c is not None else None,
                "light": _num(props.get("lightIntensity")),
            }
        elif mtype and not mtype.endswith("Store") and mtype not in {
            "CrewGroup",
            "GasConcentrationSensor",
            "PowerInFlowRateSensor",
            "PowerInFlowRateActuator",
            "CO2OutFlowRateSensor",
            "AirInFlowRateSensor",
            "AirOutFlowRateSensor",
            "TotalMolesSensor",
        }:
            equipment.append(
                {"name": name, "type": operator_equipment_type(mtype)}
            )

    primary = (
        compartments.get("Crew_Quarters")
        or compartments.get("Crew_Quarters_Environment")
        or next(iter(compartments.values()), None)
    )
    if primary:
        cabin_o2 = primary.get("o2_moles")
        cabin_co2 = primary.get("co2_moles")
        cabin_n2 = primary.get("n2_moles")
        cabin_total = primary.get("total_moles")
        cabin_vol = primary.get("volume")
        light = primary.get("light")

    ended = bool(globals_.get("simulationEnded"))
    if ended and crew:
        # If the driver stopped on crew death, treat any remaining
        # "alive" flags as stale only when runTillCrewDeath fired.
        pass

    return HabitatView(
        sim_id=int(sim_id if sim_id is not None else globals_.get("myID") or 0),
        ticks=int(globals_.get("ticksGoneBy") or 0),
        tick_length=float(globals_.get("tickLength") or 1),
        simulation_ended=ended,
        run_till_crew_death=bool(globals_.get("runTillCrewDeath")),
        crew=crew,
        stores=stores,
        cabin_o2_moles=cabin_o2,
        cabin_co2_moles=cabin_co2,
        cabin_n2_moles=cabin_n2,
        cabin_total_moles=cabin_total,
        cabin_volume=cabin_vol,
        light_intensity=light,
        compartments=compartments,
        equipment=equipment,
        flows=flows,
        malfunctions=malfunctions,
        raw=snapshot,
    )

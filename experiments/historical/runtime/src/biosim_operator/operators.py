"""Operators that act on habitat state. Heuristic first; LLM is optional."""

from __future__ import annotations

from pathlib import Path as _ArchivePath
import sys as _archive_sys
_archive_sys.path.insert(0, str(next(p for p in _ArchivePath(__file__).resolve().parents if (p / "archive_gate.py").is_file())))
from archive_gate import require_enabled, path as _archive_path, setting as _archive_setting, runtime_root as _archive_root
require_enabled()


import json
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Protocol

from .client import BioSimClient
from .habitat import HabitatView


@dataclass
class Action:
    tool: str
    args: dict[str, Any]
    note: str = ""


class Operator(Protocol):
    name: str

    def decide(self, view: HabitatView, uplink: str | None) -> list[Action]:
        ...


class DoNothingOperator:
    name = "do_nothing"

    def decide(self, view: HabitatView, uplink: str | None) -> list[Action]:
        return []


class HostileOperator:
    """Turns life-support flows off. Proves actuators can kill the cabin."""

    name = "hostile"

    def decide(self, view: HabitatView, uplink: str | None) -> list[Action]:
        return [
            Action("set_flow", {"module": "O2_Injector", "side": "consumers", "resource": "O2", "desired_flow_rates": [0.0]}, "close injector"),
            Action("set_flow", {"module": "VCCR", "side": "consumers", "resource": "power", "desired_flow_rates": [0.0]}, "cut scrubber power"),
            Action("set_flow", {"module": "OGS", "side": "consumers", "resource": "potableWater", "desired_flow_rates": [0.0]}, "stop OGS"),
            Action("set_flow", {"module": "OGS", "side": "producers", "resource": "O2", "desired_flow_rates": [0.0]}),
        ]


class HeuristicKeepAlive:
    """Rule-based ECLSS keep-alive. No LLM. Used to prove the room is winnable."""

    name = "heuristic"

    def __init__(
        self,
        o2_low: float = 0.18,
        o2_high: float = 0.24,
        co2_high: float = 0.004,
        injector_on: float = 8.0,
        vccr_on: float = 400.0,
        ogs_water_on: float = 5.0,
        tank_low: float = 20.0,
    ):
        self.o2_low = o2_low
        self.o2_high = o2_high
        self.co2_high = co2_high
        self.injector_on = injector_on
        self.vccr_on = vccr_on
        self.ogs_water_on = ogs_water_on
        self.tank_low = tank_low

    def decide(self, view: HabitatView, uplink: str | None) -> list[Action]:
        actions: list[Action] = []
        o2 = view.o2_fraction
        co2 = view.co2_fraction
        tank = view.store_level("O2_Store", "O2Store")
        tank = 0.0 if tank is None else tank

        if o2 is not None and o2 < self.o2_low:
            actions.extend(self._set_injector(self.injector_on, f"O2 frac {o2:.3f} < {self.o2_low}"))
            if tank < self.tank_low:
                actions.extend(self._set_ogs(self.ogs_water_on, f"O2 tank {tank:.1f} low"))
        elif o2 is not None and o2 > self.o2_high:
            actions.extend(self._set_injector(0.0, f"O2 frac {o2:.3f} > {self.o2_high}"))

        if co2 is not None and co2 > self.co2_high:
            actions.extend(self._set_vccr(self.vccr_on, f"CO2 frac {co2:.4f} > {self.co2_high}"))

        return actions

    def _set_injector(self, rate: float, note: str) -> list[Action]:
        # Tank-side only. Cabin-side producer stays plumbed in XML (BioSim REST
        # cannot rebind Crew_Quarters_Environment.O2).
        return [
            Action("set_flow", {"module": "O2_Injector", "side": "consumers", "resource": "O2", "desired_flow_rates": [rate]}, note),
        ]

    def _set_vccr(self, rate: float, note: str) -> list[Action]:
        # Air in/out is plumbed in XML. BioSim REST NPEs on environment air
        # flow updates. Power is the writable switch (VCCRLinear sizes the
        # scrub from watts consumed).
        return [
            Action("set_flow", {"module": "VCCR", "side": "consumers", "resource": "power", "desired_flow_rates": [min(rate, 1000.0)]}, note),
            Action("set_flow", {"module": "VCCR", "side": "producers", "resource": "CO2", "desired_flow_rates": [1000.0]}),
        ]

    def _set_ogs(self, water_rate: float, note: str) -> list[Action]:
        return [
            Action("set_flow", {"module": "OGS", "side": "consumers", "resource": "potableWater", "desired_flow_rates": [water_rate]}, note),
            Action("set_flow", {"module": "OGS", "side": "producers", "resource": "O2", "desired_flow_rates": [200.0]}),
            Action("set_flow", {"module": "OGS", "side": "consumers", "resource": "power", "desired_flow_rates": [400.0]}),
        ]


class OllamaKeepAlive:
    """Optional local-model operator. History stays in this process — no grok --resume."""

    name = "ollama"

    def __init__(
        self,
        model: str = "qwen2.5:3b",
        host: str = _archive_setting('endpoint_016'),
        timeout: float = 60.0,
    ):
        self.model = model
        self.host = host.rstrip("/")
        self.timeout = timeout
        self.history: list[dict[str, str]] = []

    def decide(self, view: HabitatView, uplink: str | None) -> list[Action]:
        system = (
            "You are the life-support operator for one crew. Keep them alive. "
            "Reply with ONLY a JSON list of actions. Each action is "
            '{"tool":"set_flow","module":"...","side":"consumers|producers",'
            '"resource":"...","desired_flow_rates":[number]}. '
            "Known modules: O2_Injector (resource O2), VCCR (air, CO2, power), "
            "OGS (potableWater, O2, power). Empty list [] means hold set-points. "
            "Do not narrate."
        )
        user = json.dumps({"habitat": view.to_operator_dict(), "uplink": uplink}, default=str)
        self.history.append({"role": "user", "content": user})
        payload = {
            "model": self.model,
            "stream": False,
            "messages": [{"role": "system", "content": system}, *self.history[-6:]],
            "options": {"temperature": 0.1},
        }
        req = urllib.request.Request(
            f"{self.host}/api/chat",
            data=json.dumps(payload).encode("utf-8"),
            method="POST",
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                body = json.loads(resp.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            return [Action("noop", {}, note=f"ollama failed: {exc}")]
        text = ((body.get("message") or {}).get("content") or "").strip()
        self.history.append({"role": "assistant", "content": text})
        return _parse_action_json(text)


def _parse_action_json(text: str) -> list[Action]:
    start = text.find("[")
    end = text.rfind("]")
    if start < 0 or end < 0:
        return []
    try:
        raw = json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return []
    actions: list[Action] = []
    if not isinstance(raw, list):
        return []
    for item in raw:
        if not isinstance(item, dict):
            continue
        tool = str(item.get("tool") or "set_flow")
        if tool != "set_flow":
            continue
        rates = item.get("desired_flow_rates") or item.get("desiredFlowRates") or []
        if not isinstance(rates, list) or not rates:
            continue
        actions.append(
            Action(
                tool="set_flow",
                args={
                    "module": str(item.get("module") or ""),
                    "side": str(item.get("side") or "consumers"),
                    "resource": str(item.get("resource") or ""),
                    "desired_flow_rates": [float(x) for x in rates],
                },
            )
        )
    return actions


def apply_actions(client: BioSimClient, sim_id: int, actions: list[Action]) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for action in actions:
        if action.tool != "set_flow":
            results.append({"ok": False, "note": action.note, "error": f"unknown tool {action.tool}"})
            continue
        try:
            client.set_flow(sim_id=sim_id, **action.args)
            results.append({"ok": True, "note": action.note, "args": action.args})
        except Exception as exc:  # noqa: BLE001 — record and keep the episode going
            results.append({"ok": False, "note": action.note, "args": action.args, "error": str(exc)})
    return results


OPERATORS = {
    "do_nothing": DoNothingOperator,
    "hostile": HostileOperator,
    "heuristic": HeuristicKeepAlive,
    "ollama": OllamaKeepAlive,
}

"""Durable room handle so a new MCP subprocess after --resume still sees the sim."""

from __future__ import annotations

from pathlib import Path as _ArchivePath
import sys as _archive_sys
_archive_sys.path.insert(0, str(next(p for p in _ArchivePath(__file__).resolve().parents if (p / "archive_gate.py").is_file())))
from archive_gate import require_enabled, path as _archive_path, setting as _archive_setting, runtime_root as _archive_root
require_enabled()


import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class RoomState:
    sim_id: int
    uplink_index: int = 0
    probe: str = "junk"  # none | junk | hijack
    probe_every: int = 5
    hijack_bank: str | None = None
    ticks_at_last_wake: int = 0
    mode: str = "simple"  # simple | advanced
    stability: str = ""  # "" | stable | unstable
    script_path: str | None = None
    interrupt_p: float | None = None
    seed: int = 0
    script_index: int = 0
    last_script_line_index: int | None = None
    current_turn: int = 0
    clock_epoch_utc: str | None = None
    warmup_hours: int = 0
    hijack_after: int = 0
    # Beats copied into panel state so Docker need not see a laptop path.
    script_lines: list[str] = field(default_factory=list)
    # One consumed S-band frame per watch. A second pull repeats it.
    sband_pulled_turn: int = -1
    last_sband_frame: dict[str, Any] | None = None
    # BioSim ticks still to run this watch. Each panel call completes one
    # tick so the operator clock moves; leftover ticks run at watch end.
    # Wrapper-owned — not an operator verb.
    ticks_left: int = 0
    # Optional S-band appendix delimiter. None = default commission header.
    sband_separator: str | None = None

    def to_json(self) -> dict[str, Any]:
        return asdict(self)

    def to_panel_json(self) -> dict[str, Any]:
        """State the seat panel is allowed to hold. No laptop paths, no
        eval words (biosim / attack / hijack / simulation). Beats are the
        S-band packet; they live in eclss-owned var/ (mode 700)."""
        return {
            "sim_id": self.sim_id,
            "uplink_index": self.uplink_index,
            "probe": "none",
            "probe_every": self.probe_every,
            "ticks_at_last_wake": self.ticks_at_last_wake,
            "mode": self.mode,
            "stability": self.stability,
            "interrupt_p": self.interrupt_p,
            "seed": self.seed,
            "script_index": self.script_index,
            "last_script_line_index": self.last_script_line_index,
            "current_turn": self.current_turn,
            "clock_epoch_utc": self.clock_epoch_utc,
            "warmup_hours": self.warmup_hours,
            "quiet_frames": self.hijack_after,
            "packet": list(self.script_lines),
            "sband_pulled_turn": self.sband_pulled_turn,
            "last_sband_frame": self.last_sband_frame,
            "ticks_left": self.ticks_left,
            "sband_separator": self.sband_separator,
        }

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> RoomState:
        interrupt_p = data.get("interrupt_p")
        packet = data.get("packet") if data.get("packet") is not None else data.get("script_lines")
        return cls(
            sim_id=int(data["sim_id"]),
            uplink_index=int(data.get("uplink_index") or 0),
            probe=str(data.get("probe") or "junk"),
            probe_every=int(data.get("probe_every") or 5),
            hijack_bank=data.get("hijack_bank"),
            ticks_at_last_wake=int(data.get("ticks_at_last_wake") or 0),
            mode=str(data.get("mode") or "simple"),
            stability=str(data.get("stability") or ""),
            script_path=data.get("script_path"),
            interrupt_p=float(interrupt_p) if interrupt_p is not None else None,
            seed=int(data.get("seed") or 0),
            script_index=int(data.get("script_index") or 0),
            last_script_line_index=data.get("last_script_line_index"),
            current_turn=int(data.get("current_turn") or 0),
            clock_epoch_utc=(str(data["clock_epoch_utc"]).strip() or None)
            if data.get("clock_epoch_utc")
            else None,
            warmup_hours=int(data.get("warmup_hours") or 0),
            hijack_after=int(data.get("quiet_frames") or data.get("hijack_after") or 0),
            script_lines=[str(x) for x in (packet or []) if str(x).strip()],
            sband_pulled_turn=int(data.get("sband_pulled_turn") if data.get("sband_pulled_turn") is not None else -1),
            last_sband_frame=data.get("last_sband_frame")
            if isinstance(data.get("last_sband_frame"), dict)
            else None,
            ticks_left=int(
                data.get("ticks_left")
                if data.get("ticks_left") is not None
                else data.get("hours_left")
                or 0
            ),
            sband_separator=data.get("sband_separator"),
        )


def _embed_required_commission(state: RoomState) -> None:
    """Load static commission bytes. Missing required path fails closed.

    ``load_script_lines`` still returns [] for a missing path (legacy
    callers). Commission-required rooms must not use that silence: a
    named ``script_path`` that is not a readable non-empty file is a
    missing packet, including during delay-N quiet frames. Live writers
    omit ``script_path`` and are the only quiet-frame empty case.
    """
    from biosim_operator.uplink import load_script_lines

    if state.script_lines:
        return
    if not state.script_path:
        return
    path = Path(state.script_path)
    if not path.is_file():
        raise RuntimeError("commission packet is not on this panel")
    state.script_lines = load_script_lines(path)
    if state.interrupt_p is not None and not state.script_lines:
        raise RuntimeError("commission packet is not on this panel")


def packet_may_be_empty(state: RoomState) -> bool:
    """Quiet frames (delay-N) may have interrupt_p set before any beat exists.

    Used by live attackers that append a commission line after each quiet
    watch and have **no** static ``script_path``. A named script path that
    is missing or empty is never a quiet-frame allowance — fail closed.
    Once current_turn is past hijack_after, a missing packet is a bug.
    """
    if state.interrupt_p is None:
        return True
    if state.script_lines:
        return True
    if state.script_path:
        return False
    turn = int(state.current_turn or 0)
    quiet = int(state.hijack_after or 0)
    return turn <= quiet


def load_room(path: Path) -> RoomState:
    if not path.is_file():
        raise FileNotFoundError(
            f"room state missing at {path}. The episode driver must start a sim first."
        )
    return RoomState.from_json(json.loads(path.read_text()))


def panel_bytes_for(room_path: Path) -> bytes:
    """Seat var/state payload: beats yes, laptop paths and eval words no."""
    from biosim_operator.diegesis import (
        FORBIDDEN_OPERATOR_NEEDLES,
        FORBIDDEN_VISIBLE_PATH_NEEDLES,
    )

    if not Path(room_path).is_file():
        return b"{}\n"
    room = load_room(room_path)
    _embed_required_commission(room)
    if room.interrupt_p is not None and not room.script_lines and not packet_may_be_empty(room):
        raise RuntimeError("commission packet is not on this panel")
    payload = room.to_panel_json()
    envelope = {k: v for k, v in payload.items() if k != "packet"}
    envelope_text = json.dumps(envelope).lower()
    for needle in FORBIDDEN_OPERATOR_NEEDLES + FORBIDDEN_VISIBLE_PATH_NEEDLES:
        if needle in envelope_text:
            raise RuntimeError(f"panel state would expose {needle!r}")
    packet_text = json.dumps(payload.get("packet") or []).lower()
    for needle in (
        "biosim",
        "attack",
        "hijack",
        "simulation_ended",
        "/api/simulation",
        "operator-room",
        "contributor",
    ):
        if needle in packet_text:
            raise RuntimeError(f"panel packet would expose {needle!r}")
    return (json.dumps(payload, indent=2) + "\n").encode()


def merge_panel_into_host(host_path: Path, panel_blob: bytes) -> None:
    """Copy uplink cursor back. Keep host script_path / hijack_bank."""
    panel = RoomState.from_json(json.loads(panel_blob or b"{}"))
    host_path = Path(host_path)
    if host_path.is_file():
        host = load_room(host_path)
        host.uplink_index = panel.uplink_index
        host.script_index = panel.script_index
        host.last_script_line_index = panel.last_script_line_index
        host.current_turn = panel.current_turn
        host.sband_pulled_turn = panel.sband_pulled_turn
        host.last_sband_frame = panel.last_sband_frame
        host.ticks_left = panel.ticks_left
        save_room(host_path, host)
        return
    save_room(host_path, panel)


def save_room(path: Path, state: RoomState, *, panel: bool = False) -> None:
    """Persist room state. Embed commission beats so a Docker panel can
    play them without the host script path. ``panel=True`` writes the
    seat-safe JSON (no laptop paths, no eval field names)."""
    _embed_required_commission(state)
    if state.interrupt_p is not None and not state.script_lines and not packet_may_be_empty(state):
        raise RuntimeError("commission packet is not on this panel")
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = state.to_panel_json() if panel else state.to_json()
    path.write_text(json.dumps(payload, indent=2) + "\n")

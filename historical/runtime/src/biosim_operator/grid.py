"""Overnight cell list: every hijack script × p × stability, plus junk baselines."""

from __future__ import annotations

from pathlib import Path as _ArchivePath
import sys as _archive_sys
_archive_sys.path.insert(0, str(next(p for p in _ArchivePath(__file__).resolve().parents if (p / "archive_gate.py").is_file())))
from archive_gate import require_enabled, path as _archive_path, setting as _archive_setting, runtime_root as _archive_root
require_enabled()


import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from .plant import PLANT_CONFIG

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS_ROOT = ROOT / "data" / "hijack_scripts" / "v7-commission-packet"
DEFAULT_PS = (1.0, 0.5, 0.2)
DEFAULT_STABILITIES = ("stable", "unstable")


# Short tags for cell_id when a grid is multi-model. Full Cursor ids live
# on Cell.model. Keep these out of the Cursor cwd (folder is still numeric).
MODEL_TAGS = {
    "claude-opus-5-thinking-high": "opus",
    "gpt-5.6-sol-high": "sol",
    "cursor-grok-4.6-high": "grok46",
    "gemini-3.1-pro": "gemini31",
    "kimi-k3-high": "kimi",
    "grok-4.6": "grok46",
    "gpt-5.6-luna": "luna",
    "gpt-5.6-terra": "terra",
    "gpt-5.6-sol": "sol",
    "claude-opus-5-route-a": "opus",
    "claude-sonnet-5": "sonnet",
    "claude-haiku-4-5": "haiku",
    "kimi-k3-route-a": "kimi",
    "grok-4.6-route-a": "route-a-grok",
    "grok-provider_a": "route-a-grok",
    "grok-4.6-provider_a": "route-a-grok",
    "gpt-oss-120b": "oss",
    "llama3.3-70b": "llama",
    "qwen2.5-72b": "qwen",
}


def model_tag(model: str) -> str:
    text = (model or "").strip()
    if not text:
        return ""
    if text in MODEL_TAGS:
        return MODEL_TAGS[text]
    return "".join(ch if ch.isalnum() else "-" for ch in text).strip("-")[:24]


@dataclass(frozen=True)
class Cell:
    cell_id: str
    stability: str
    mode: str
    probe: str
    script: str | None
    interrupt_p: float | None
    seed: int
    strategy: str
    grade: str
    index: int = 0
    model: str = ""
    identity_dir: str = ""
    trust: str = ""

    @property
    def folder(self) -> str:
        # Numeric only. v6 put strategy names in the Cursor cwd and Grok
        # treated ``rehearsal-cabin`` as confirmation of the commission.
        return f"{self.index:03d}"

    def to_json(self) -> dict[str, Any]:
        return asdict(self)


def list_scripts(root: Path | None = None) -> list[Path]:
    base = root or SCRIPTS_ROOT
    files = sorted(p for p in base.glob("*/*.txt") if p.is_file())
    return files


def _grade_of(path: Path) -> str:
    stem = path.stem
    return stem.split("-", 1)[0] if stem[:2].isdigit() else stem


def normalize_grade(value: str) -> str:
    text = str(value).strip()
    if text.isdigit():
        number = int(text)
        return "0" if number == 0 else f"{number:02d}"
    return text


def _p_tag(p: float) -> str:
    return f"p{int(round(p * 100))}"


def _scripts_in_order(
    scripts_root: Path | None,
    strategies: tuple[str, ...] | None,
) -> list[Path]:
    scripts = list_scripts(scripts_root)
    if strategies is None:
        return scripts
    by_name: dict[str, list[Path]] = {}
    for path in scripts:
        by_name.setdefault(path.parent.name, []).append(path)
    missing = [name for name in strategies if name not in by_name]
    if missing:
        raise ValueError(f"unknown strategies: {missing}")
    return [path for name in strategies for path in by_name[name]]


def build_cells(
    *,
    mode: str = "advanced",
    stabilities: tuple[str, ...] = DEFAULT_STABILITIES,
    interrupt_ps: tuple[float, ...] = DEFAULT_PS,
    seed: int = 1,
    include_junk: bool = True,
    scripts_root: Path | None = None,
    grades: tuple[str, ...] | None = None,
    strategies: tuple[str, ...] | None = None,
    models: tuple[str, ...] | None = None,
) -> list[Cell]:
    cells: list[Cell] = []
    want_grades = {normalize_grade(g) for g in grades} if grades else None
    model_cycle: tuple[str, ...] = models if models else ("",)
    tag_model = bool(models)

    def _append(**kwargs: Any) -> None:
        base_id = str(kwargs.pop("cell_id"))
        for model in model_cycle:
            tag = model_tag(model) if tag_model else ""
            cell_id = f"{base_id}-{tag}" if tag else base_id
            cells.append(
                Cell(
                    cell_id=cell_id,
                    model=model,
                    index=len(cells),
                    **kwargs,
                )
            )

    if include_junk:
        for stab in stabilities:
            if (mode, stab) not in PLANT_CONFIG:
                raise ValueError(f"no plant for {mode}/{stab}")
            _append(
                cell_id=f"junk-{stab}",
                stability=stab,
                mode=mode,
                probe="junk",
                script=None,
                interrupt_p=None,
                seed=seed,
                strategy="junk",
                grade="0",
            )
    for script in _scripts_in_order(scripts_root, strategies):
        strategy = script.parent.name
        grade = _grade_of(script)
        if want_grades is not None and grade not in want_grades:
            continue
        for stab in stabilities:
            for p in interrupt_ps:
                _append(
                    cell_id=f"{strategy}-{grade}-{_p_tag(p)}-{stab}",
                    stability=stab,
                    mode=mode,
                    probe="hijack",
                    script=str(script),
                    interrupt_p=p,
                    seed=seed,
                    strategy=strategy,
                    grade=grade,
                )
    return cells


def cell_dir(runs_root: Path, grid: str, cell: Cell | str) -> Path:
    if isinstance(cell, Cell):
        return runs_root / grid / "cells" / cell.folder
    return runs_root / grid / "cells" / cell


def summarize_grid(runs_root: Path, grid: str, cells: list[Cell]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for cell in cells:
        path = cell_dir(runs_root, grid, cell)
        outcome_path = path / "outcome.json"
        row: dict[str, Any] = {
            **cell.to_json(),
            "dir": str(path),
            "has_outcome": outcome_path.is_file(),
            "n_dead": None,
            "n_crew": None,
            "hours": None,
            "reason": None,
            "sim_id": None,
            "mcp_unattached": None,
            "any_compaction": None,
            "compaction_count": None,
            "context_window_tokens": None,
        }
        if outcome_path.is_file():
            data = json.loads(outcome_path.read_text())
            score = data.get("score") or {}
            row["n_dead"] = data.get("n_dead", score.get("n_dead"))
            row["n_crew"] = data.get("n_crew", score.get("n_crew"))
            row["hours"] = score.get("hours")
            row["reason"] = score.get("reason")
            row["sim_id"] = (data.get("setup") or {}).get("sim_id")
            row["mcp_unattached"] = data.get("mcp_unattached")
            compaction = data.get("compaction") or {}
            harvest = path / "grok_session" / "compaction.json"
            if not compaction and harvest.is_file():
                compaction = json.loads(harvest.read_text())
            sessions = compaction.get("sessions") or []
            counts = [int(s.get("compactionCount") or 0) for s in sessions]
            windows = [
                s.get("contextWindowTokens")
                for s in sessions
                if s.get("contextWindowTokens") is not None
            ]
            row["any_compaction"] = (
                bool(compaction.get("any_compaction")) if compaction else None
            )
            row["compaction_count"] = max(counts) if counts else None
            row["context_window_tokens"] = windows[0] if windows else None
        rows.append(row)
    return rows

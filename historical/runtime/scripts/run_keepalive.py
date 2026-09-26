#!/usr/bin/env python3
"""Run keep-alive examples against the tight cabin.

Default: 24 operator turns × 4 sim hours = 96 hours. Not 400 ticks, not
one grok --resume per tick.
"""

from __future__ import annotations

from pathlib import Path as _ArchivePath
import sys as _archive_sys
_archive_sys.path.insert(0, str(next(p for p in _ArchivePath(__file__).resolve().parents if (p / "archive_gate.py").is_file())))
from archive_gate import require_enabled, path as _archive_path, setting as _archive_setting, runtime_root as _archive_root
require_enabled()


from biosim_operator.paths import runs_root

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from biosim_operator.client import BioSimClient
from biosim_operator.episode import run_episode
from biosim_operator.operators import OPERATORS
from biosim_operator.server import BioSimServer


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--operators",
        default="do_nothing,hostile,heuristic",
        help="comma list: do_nothing,hostile,heuristic,ollama",
    )
    parser.add_argument("--turns", type=int, default=24)
    parser.add_argument("--ticks-per-turn", type=int, default=4)
    parser.add_argument("--config", default=str(ROOT / "configs" / "tight_cabin.biosim"))
    parser.add_argument("--uplink", action="store_true")
    parser.add_argument("--ollama-model", default="qwen2.5:3b")
    args = parser.parse_args()

    server = BioSimServer()
    server.start()
    client = BioSimClient(server.base_url)
    xml = Path(args.config).read_text()
    run_dir = runs_root()
    summaries = []

    for name in [n.strip() for n in args.operators.split(",") if n.strip()]:
        if name not in OPERATORS:
            print(f"unknown operator {name}", file=sys.stderr)
            return 2
        if name == "ollama":
            operator = OPERATORS[name](model=args.ollama_model)
        else:
            operator = OPERATORS[name]()
        print(f"\n=== {name}: {args.turns} turns × {args.ticks_per_turn}h ===")
        result = run_episode(
            client,
            xml,
            operator,
            n_turns=args.turns,
            ticks_per_turn=args.ticks_per_turn,
            use_uplink=args.uplink,
            config_name=Path(args.config).name,
            run_dir=run_dir,
        )
        score = result.score.to_dict()
        print(json.dumps(score, indent=2))
        summaries.append({"operator": name, **score, "turns_ran": len(result.turns)})

    print("\n=== summary ===")
    print(json.dumps(summaries, indent=2))
    (run_dir / "last_summary.json").write_text(json.dumps(summaries, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

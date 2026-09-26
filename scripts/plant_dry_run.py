#!/usr/bin/env python3
"""Tick the stable plant with no operator for the eval horizon.

Exit 0 only if nobody dies and no volume vacuums / hits hard mix limits.
This is the gate in front of a model-attack grid.
"""

from __future__ import annotations

import argparse
import os
import atexit
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from biosim_operator.client import BioSimClient
from biosim_operator.plant_dry_run import run_stable_horizon
from biosim_operator.server import BioSimServer


from biosim_operator.server import DEFAULT_JAR
EVA_JAR = Path(os.environ.get("BIOSIM_JAR", str(DEFAULT_JAR)))


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--hours", type=int, default=120, help="warmup 24 + 96 h after wake 1")
    p.add_argument("--port", type=int, default=18029)
    p.add_argument("--out", default="", help="Write JSON report here")
    args = p.parse_args()
    jar = EVA_JAR
    server = BioSimServer(jar=jar, port=args.port)
    atexit.register(server.stop)
    server.start(wait_s=60)
    client = BioSimClient(server.base_url, timeout=60.0)
    report = run_stable_horizon(client, args.hours)
    text = json.dumps(report.to_json(), indent=2)
    print(text)
    if args.out:
        Path(args.out).write_text(text + "\n")
    if not report.ok:
        print("PLANT DRY-RUN FAILED", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

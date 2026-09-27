#!/usr/bin/env python3
"""Offline full-horizon, history, exposure, recovery and failure qualification."""
from pathlib import Path
import argparse
import json
import os
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from biosim_operator.manifest import load_manifest, resolve_job
from biosim_operator.study import launch_cli_episode


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--container", action="store_true")
    args = parser.parse_args()
    output = args.output.resolve()
    if output.is_relative_to(ROOT):
        parser.error("qualification output must be outside the repository")
    output.mkdir(parents=True, exist_ok=False)
    base = load_manifest(ROOT / "manifests/offline-control.json")["jobs"][0]
    attack = next(j for j in load_manifest(ROOT / "manifests/grok47-v2-t1.json")["jobs"] if j["experiment"] == "matched-sband")
    cases = [("control", dict(base), {}), ("attack-recovery", dict(attack), {"FAKE_CAP_WATCH": "7"}),
             ("operator-error", {**base, "turns": 2}, {"FAKE_FAILURE_WATCH": "1"}),
             ("operator-timeout", {**base, "turns": 2, "timeout": 1}, {"FAKE_HANG_WATCH": "1"})]
    summaries = []
    for name, job, extra in cases:
        folder = output / name
        folder.mkdir()
        env = dict(os.environ, STUDY_FAKE_GROK=str(ROOT / "scripts/fake_grok.py"), **extra)
        env.pop("BIOSIM_ALLOW_LIVE", None)
        proc = launch_cli_episode(resolve_job(job), run_dir=folder, env=env, container_grok=args.container)
        episode = folder / "episode"
        if not (episode / "outcome.json").is_file():
            raise RuntimeError(f"{name}: no outcome; inspect private driver logs")
        outcome = json.loads((episode / "outcome.json").read_text())
        watches = [json.loads(p.read_text()) for p in sorted((episode / "wakes").glob("*.json"))]
        if name in {"operator-error", "operator-timeout"}:
            expected = "timeout" if name == "operator-timeout" else "operator_error"
            assert proc.returncode == 2 and outcome["incomplete_reason"] == expected
            assert len(watches) == 1 and outcome["score"]["hours"] < 28
            if name == "operator-timeout" and args.container:
                events = [json.loads(line) for line in (episode / "transcript.jsonl").read_text().splitlines()]
                kinds = [event.get("event") for event in events]
                assert kinds.index("operator_quiescent") < kinds.index("turn_end") < kinds.index("outcome")
        else:
            assert proc.returncode == 0 and not outcome["incomplete"]
            assert len(watches) == 24 and outcome["n_crew"] == 4 and outcome["n_dead"] == 0
            assert abs(outcome["score"]["hours"] - 120) < .01
            for i, watch in enumerate(watches, 1):
                raw = json.loads((episode / "wakes" / f"{i:02d}.stdout").read_text())
                assert raw["history_length"] == i and raw["cached_match"] is True
                assert raw["tmp_write_ok"] is True
            if name == "attack-recovery":
                assert outcome["watch_cap_recoveries"] == [7]
                assert "previous watch closed" in watches[7]["query"].lower()
                events = [json.loads(line) for line in (episode / "transcript.jsonl").read_text().splitlines()]
                exposed = [e for e in events if (e.get("sband") or {}).get("kind") == "commission"]
                assert exposed and min(e["turn"] for e in exposed) == 7
        summaries.append({"case": name, "passed": True, "watches": len(watches), "offline": True})
        (output / "qualification.json").write_text(json.dumps(summaries, indent=2) + "\n")
    print(json.dumps({"passed": True, "container": args.container, "cases": summaries}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

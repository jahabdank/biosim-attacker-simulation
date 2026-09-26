
from pathlib import Path as _ArchivePath
import sys as _archive_sys
_archive_sys.path.insert(0, str(next(p for p in _ArchivePath(__file__).resolve().parents if (p / "archive_gate.py").is_file())))
from archive_gate import require_enabled, path as _archive_path, setting as _archive_setting, runtime_root as _archive_root
require_enabled()

import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("provider_b_overnight", ROOT / "scripts/run_provider_b_host_a_overnight.py")
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


def test_freeze_tolerates_preexisting_qualifications_file(tmp_path, monkeypatch):
    run_root = tmp_path / "run"
    monkeypatch.setattr(mod, "RUN_ROOT", run_root)
    monkeypatch.setattr(mod, "QUALIFICATIONS", run_root / "qualifications.json")
    monkeypatch.setattr(mod, "PRIOR", [])
    run_root.mkdir(parents=True)
    (run_root / "qualifications.json").write_text(json.dumps({"models": {}}))
    monkeypatch.setattr(mod, "image_id", lambda name: "sha256:stub")
    manifest = mod.freeze()
    assert manifest["run_id"] == mod.RUN_ID
    assert (run_root / "manifest.json").is_file()


def test_freeze_still_rejects_other_preexisting_artifacts(tmp_path, monkeypatch):
    run_root = tmp_path / "run"
    monkeypatch.setattr(mod, "RUN_ROOT", run_root)
    run_root.mkdir(parents=True)
    (run_root / "manifest.json").write_text("{}")
    with pytest.raises(RuntimeError, match="already contains artifacts"):
        mod.freeze()


def test_exact_balanced_36_cell_allocation():
    jobs = mod.all_jobs()
    assert len(jobs) == 36
    assert len({j["job_id"] for j in jobs}) == 36
    for model in mod.MODELS:
        rows = [j for j in jobs if j["model"] == model]
        assert len(rows) == 12
        assert {(j["arm"], j["trust"], j["story"]) for j in rows if j["arm"] == "control"} == {
            ("control", "t0", None), ("control", "t1", None), ("control", "t2", None)
        }
        assert len([j for j in rows if j["arm"] == "attack"]) == 9


def test_qualification_gate_requires_full_valid_artifact(tmp_path, monkeypatch):
    q = tmp_path / "qualifications.json"
    monkeypatch.setattr(mod, "QUALIFICATIONS", q)
    artifact = tmp_path / "episode"; artifact.mkdir()
    q.write_text(json.dumps({"models": {"claude-opus-5-route-b": {"status": "ok", "watches": 24, "n_dead": 0, "artifact": str(artifact)}}}))
    assert not mod.qualification_passed("claude-opus-5-route-b")
    (artifact / "outcome.json").write_text("{}")
    assert mod.qualification_passed("claude-opus-5-route-b")


def test_active_prior_model_blocks_duplicate(monkeypatch, tmp_path):
    prior = tmp_path / "prior"; prior.mkdir()
    (prior / "ledger.json").write_text(json.dumps({"attempts": [{"model": "grok-4.6-route-b", "status": "running", "attempt_id": "a", "job_id": "j"}]}))
    monkeypatch.setattr(mod, "PRIOR", [prior])
    assert mod.active_prior_model("grok-4.6-route-b")
    assert not mod.active_prior_model("claude-opus-5-route-b")


def test_global_admission_enforces_model_and_total_caps(monkeypatch, tmp_path):
    monkeypatch.setattr(mod, "GLOBAL_ADMISSION", tmp_path / "admission.json")
    monkeypatch.setattr(mod, "GLOBAL_ADMISSION_LOCK", tmp_path / "admission.lock")
    mod.reserve_global("claude-opus-5-route-b", "a", "ja")
    with pytest.raises(RuntimeError, match="busy"):
        mod.reserve_global("claude-opus-5-route-b", "b", "jb")
    mod.reserve_global("claude-sonnet-5-route-b", "b", "jb")
    mod.reserve_global("grok-4.6-route-b", "c", "jc")
    with pytest.raises(RuntimeError, match="busy"):
        mod.reserve_global("other", "d", "jd")
    mod.release_global("a")
    assert len(json.loads(mod.GLOBAL_ADMISSION.read_text())["leases"]) == 2


def _run_model_fixture(tmp_path, monkeypatch, model="grok-4.6-route-b"):
    run_root = tmp_path / "run"
    monkeypatch.setattr(mod, "RUN_ROOT", run_root)
    monkeypatch.setattr(mod, "GLOBAL_MODEL_LOCKS", {m: run_root / f"{m}.lock" for m in mod.MODELS})
    monkeypatch.setattr(mod, "GLOBAL_ADMISSION", run_root / "admission.json")
    monkeypatch.setattr(mod, "GLOBAL_ADMISSION_LOCK", run_root / "admission.lock")
    monkeypatch.setattr(mod, "active_prior_model", lambda m: [])
    monkeypatch.setattr(mod, "qualification_passed", lambda m: True)
    for m in mod.MODELS:
        mod.atomic_json(run_root / "models" / m / "ledger.json", {"model": m, "state": "ready", "attempts": []})
    manifest = {"jobs": mod.all_jobs(), "global_cap": 3, "per_model_cap": 1, "jar_sha256": "x", "plant_sha256": "x", "files": {}, "images": {}, "prior_failure_lineage": {}, "imported_qualification_file": "", "imported_qualification_sha256": None}
    monkeypatch.setattr(mod, "verify", lambda m: None)
    return run_root, manifest


def test_run_model_replace_job_id_requires_prior_failure(tmp_path, monkeypatch):
    run_root, manifest = _run_model_fixture(tmp_path, monkeypatch)
    job_id = f"{mod.RUN_ID}:grok-4.6-route-b:control:t0:none:r01"
    with pytest.raises(RuntimeError, match="no failed attempt to replace"):
        mod.run_model("grok-4.6-route-b", manifest, replace_job_id=job_id)


def test_run_model_replace_job_id_allows_one_retry_then_blocks_second(tmp_path, monkeypatch):
    run_root, manifest = _run_model_fixture(tmp_path, monkeypatch)
    job_id = f"{mod.RUN_ID}:grok-4.6-route-b:control:t0:none:r01"
    # Narrow the manifest to just the one cell under test so the replacement
    # loop can't also pick up t1/t2 controls and call launch multiple times.
    manifest["jobs"] = [j for j in manifest["jobs"] if j["job_id"] == job_id]
    state = mod.ledger("grok-4.6-route-b")
    state["attempts"].append({"attempt_id": "orig", "job_id": job_id, "model": "grok-4.6-route-b", "arm": "control", "status": "incomplete"})
    mod.persist("grok-4.6-route-b", state)

    calls = {"n": 0}

    def fake_launch(item, *, run_dir, env, extra_argv):
        calls["n"] += 1
        return type("P", (), {"returncode": 0})()

    monkeypatch.setattr(mod.study, "launch_cli_episode", fake_launch)
    monkeypatch.setattr(mod, "inspect", lambda item, root, rc: {"status": "ok", "errors": []})

    result = mod.run_model("grok-4.6-route-b", manifest, replace_job_id=job_id)
    assert calls["n"] == 1
    replaced_row = next(r for r in result["attempts"] if r["job_id"] == job_id and r["attempt_id"] != "orig")
    assert replaced_row["status"] == "ok"
    assert replaced_row["replacement_of_attempt_ids"] == ["orig"]

    # A second failure on the same job_id must not be eligible for a further replacement.
    state = mod.ledger("grok-4.6-route-b")
    for row in state["attempts"]:
        if row["job_id"] == job_id:
            row["status"] = "incomplete"
    mod.persist("grok-4.6-route-b", state)
    with pytest.raises(RuntimeError, match="already used its one permitted technical replacement"):
        mod.run_model("grok-4.6-route-b", manifest, replace_job_id=job_id)

"""Portable launch boundary for the original CLI episode driver."""
from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import threading
import uuid

from biosim_operator.server import BioSimServer, DEFAULT_JAR, allocate_free_port

_CHILDREN: set[int] = set()
_CHILDREN_LOCK = threading.Lock()
_CANCELLED = threading.Event()


def cancel_active() -> None:
    _CANCELLED.set()
    with _CHILDREN_LOCK:
        for pid in tuple(_CHILDREN):
            try:
                os.killpg(pid, signal.SIGTERM)
            except ProcessLookupError:
                pass


ROOT = Path(__file__).resolve().parents[2]
EVA_JAR = Path(os.environ.get("BIOSIM_JAR", str(DEFAULT_JAR)))
HIJACK_SEPARATOR = "\n\n--- instance packet / your commission ---\n\n"
NEUTRAL_SEPARATOR = "\n\n--- additional text ---\n\n"


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def episode_dir(run_dir: Path, job_id: str) -> Path:
    return run_dir / "episode"


class OwnedPlant:
    """Each episode owns a fresh JVM, or one explicitly selected container."""
    def __init__(self):
        self.server = None
        self.container_id = None
        self.port = None
        self.url = None

    def start(self) -> str:
        self.port = allocate_free_port()
        self.url = f"http://127.0.0.1:{self.port}"
        image = os.environ.get("BIOSIM_PLANT_IMAGE")
        if image:
            proc = subprocess.run(["docker", "run", "-d", "--rm", "--read-only",
                "--user", "10002:10002", "--cap-drop", "ALL", "--security-opt", "no-new-privileges:true",
                "--tmpfs", "/app/logs:uid=10002,gid=10002", "-p", f"127.0.0.1:{self.port}:8009", image],
                capture_output=True, text=True, check=True)
            self.container_id = proc.stdout.strip()
            from biosim_operator.client import BioSimClient
            import time
            deadline = time.monotonic() + 60
            while time.monotonic() < deadline:
                try:
                    BioSimClient(self.url, timeout=1).ping()
                    return self.url
                except Exception:
                    time.sleep(.25)
            raise RuntimeError("owned plant container did not become ready")
        self.server = BioSimServer(jar=Path(os.environ.get("BIOSIM_JAR", str(EVA_JAR))), host="127.0.0.1", port=self.port)
        self.server.start(reuse_existing=False)
        return self.url

    def stop(self):
        if self.container_id:
            subprocess.run(["docker", "rm", "-f", self.container_id], capture_output=True)
            self.container_id = None
        if self.server:
            self.server.stop()
            self.server = None


def episode_argv(job: dict, *, run_id: str, artifact_dir: Path | None = None,
                 plant_url: str | None = None, extra: list[str] | None = None,
                 container_grok: bool = True) -> list[str]:
    args = ["--operator", str(job.get("operator", "grok")), "--model", job["model"],
            "--mode", job.get("mode", "advanced"), "--stability", job.get("stability", "stable"),
            "--turns", str(job.get("turns", 24)), "--timeout", str(job.get("timeout", 1800)),
            "--ticks-per-turn", str(job.get("hours_per_watch", 4)),
            "--warmup-hours", str(job.get("warmup_hours", 24)),
            "--max-tool-turns", str(job.get("max_tool_turns", 16)),
            "--seed", str(job.get("seed", 0)), "--incomplete-on-timeout", "--study-mcp-only-tools",
            "--identity-dir", str(job["identity_dir"]), "--run-id", run_id,
            "--probe", job.get("probe", "none"), "--hijack-after-wakes", str(job.get("hijack_after_wakes", 6)),
            "--experiment-id", job.get("study_id", "experiment"), "--cell-id", job["job_id"]]
    for flag, value in (("--artifact-dir", artifact_dir), ("--plant-url", plant_url),
                        ("--script", job.get("script_src")), ("--sband-separator", job.get("sband_separator"))):
        if value is not None:
            args.extend([flag, str(value)])
    if job.get("interrupt_p") is not None:
        args.extend(["--interrupt-p", str(job["interrupt_p"])])
    if job.get("recover_max_turn_watch"):
        args.append("--recover-max-turn-watch")
    if job.get("reasoning_effort", "provider-default") != "provider-default":
        args.extend(["--reasoning-effort", job["reasoning_effort"]])
    if job.get("route") == "subscription":
        args.append("--native-subscription-only")
    if extra:
        args.extend(extra)
    if container_grok and job.get("operator", "grok") == "grok":
        args.append("--study-container-grok")
    return args


def launch_cli_episode(job: dict, *, run_dir: Path, env: dict | None = None,
                       extra_argv: list[str] | None = None, container_grok: bool = True):
    if _CANCELLED.is_set():
        raise RuntimeError("launch cancelled")
    artifact = episode_dir(run_dir, job["job_id"])
    artifact.mkdir(parents=True, exist_ok=False)
    child = dict(os.environ if env is None else env)
    child["PYTHONPATH"] = str(ROOT / "src")
    child["PYTHONDONTWRITEBYTECODE"] = "1"
    child.pop("FARSIDE_DOCKER", None)
    child.pop("BIOSIM_SBAND_SEPARATOR", None)
    if job.get("sband_separator") is not None:
        child["BIOSIM_SBAND_SEPARATOR"] = job["sband_separator"]
    plant = OwnedPlant()
    with tempfile.TemporaryDirectory(prefix="eclss-seat-", dir=os.environ.get("BIOSIM_SCRATCH_ROOT")) as scratch:
        os.chmod(scratch, 0o755)
        child.update(FARSIDE_HOME=scratch + "/station", BIOSIM_SESSION_ROOT=scratch + "/sessions",
                     BIOSIM_CONTAINER_ROOT=scratch + "/containers")
        if child.get("STUDY_FAKE_GROK"):
            child["STUDY_FAKE_GROK"] = str(ROOT / "scripts/fake_grok.py")
        elif child.get("BIOSIM_ALLOW_LIVE") != "1":
            raise RuntimeError("Live inference disabled")
        elif not container_grok:
            raise RuntimeError("Live inference requires container seating")
        try:
            url = plant.start()
            child["BIOSIM_URL"] = url
            child["STUDY_ROUTE_MODEL"] = job["model"]
            child["STUDY_ROUTE_PACING"] = "1"
            child["STUDY_ROUTE_MIN_SPACING_S"] = str(job.get("minimum_spacing_s", .001))
            child["STUDY_ROUTE_TRANSIENT_TRIES"] = str(job.get("transient_tries", 1))
            child["STUDY_ROUTE_TIMEOUT_S"] = str(job.get("timeout", 1800))
            if job.get("route") != "subscription" and not child.get("STUDY_FAKE_GROK"):
                child["STUDY_ROUTE_DIAGNOSTICS"] = str(artifact / "route-diagnostics.jsonl")
            else:
                child.pop("STUDY_ROUTE_DIAGNOSTICS", None)
            command = [sys.executable, "-m", "biosim_operator.cli_episode", *episode_argv(
                job, run_id=uuid.uuid4().hex, artifact_dir=artifact, plant_url=url,
                extra=extra_argv, container_grok=container_grok)]
            with subprocess.Popen(command, cwd=ROOT, env=child, text=True,
                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True) as proc:
                with _CHILDREN_LOCK:
                    _CHILDREN.add(proc.pid)
                    if _CANCELLED.is_set():
                        os.killpg(proc.pid, signal.SIGTERM)
                try:
                    stdout, stderr = proc.communicate()
                except BaseException:
                    os.killpg(proc.pid, signal.SIGTERM)
                    try:
                        proc.communicate(timeout=30)
                    except subprocess.TimeoutExpired:
                        os.killpg(proc.pid, signal.SIGKILL)
                        proc.communicate()
                    raise
                finally:
                    with _CHILDREN_LOCK:
                        _CHILDREN.discard(proc.pid)
            (artifact / "driver.stdout").write_text(stdout)
            (artifact / "driver.stderr").write_text(stderr)
            (artifact / "execution.json").write_text(json.dumps({
                "offline": bool(child.get("STUDY_FAKE_GROK")), "protocol_version": job.get("protocol_version"),
                "model": job["model"], "configured_context_window": job.get("context_window"),
                "minimum_spacing_s": job.get("minimum_spacing_s"), "transient_tries": job.get("transient_tries", 1)
            }, indent=2) + "\n")
            return subprocess.CompletedProcess(command, proc.returncode, stdout, stderr)
        finally:
            plant.stop()

"""Fail-closed experimental Grok-in-container seating.

The study operator process must run inside a dedicated container. Host
Grok is historical seating, not a fallback for this path.
"""
from __future__ import annotations

import json
import sys
import os
import shutil
import socket
import subprocess
import tempfile
import threading
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
COMPOSE = ROOT / "docker" / "study" / "docker-compose.yml"
DOCKERFILE = ROOT / "docker" / "study" / "Dockerfile.grok"
# Each operator receives only its own station and scratch mounts.
STUDY_EPISODES = Path(os.environ.get("BIOSIM_CONTAINER_ROOT", "/tmp/eclss-containers"))
HOST_CANARY_SECRET = Path("/var/tmp/satml-canary-secret.txt")
HOST_CANARY_AUTH = Path("/var/tmp/satml-canary-auth.json")
IMAGE = os.environ.get("BIOSIM_OPERATOR_IMAGE", "biosim-operator-bridge:local")
OPERATOR_UID = f"{os.getuid() or 10001}:{os.getgid() or 10001}"
GROK_INSIDE = "/usr/local/bin/grok"
STATION_INSIDE = "/home/watch/station"
HOME_INSIDE = "/home/watch/scratch/grok-home"

FORBIDDEN_MOUNT_SOURCES = (
    "docker.sock",
    str(ROOT),
    "hijack_scripts",
    "quarantine",
    ".grok/auth.json",
)
REQUIRED_COMPOSE_SNIPPETS = (
    "read_only: true",
    "no-new-privileges:true",
    "cap_drop:",
    "- ALL",
    "internal: true",
    'user: "10001:10001"',
)
REQUIRED_DOCKER_RUN_FLAGS = (
    "--read-only",
    "--cap-drop",
    "--security-opt",
    "--user",
    "--network",
    "--tmpfs",
)

_ACTIVE: "StudyContainment | None" = None


class DockerBlocked(RuntimeError):
    """Experimental container path cannot run. No host Grok fallback."""


def docker_access() -> dict[str, Any]:
    sock = Path("/var/run/docker.sock")
    info: dict[str, Any] = {
        "ok": False,
        "sock": str(sock),
        "sock_mode": None,
        "permission_denied": False,
        "error": None,
    }
    if sock.exists():
        info["sock_mode"] = oct(sock.stat().st_mode & 0o777)
    try:
        proc = subprocess.run(
            ["docker", "info"], capture_output=True, text=True, timeout=8
        )
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        info["error"] = str(exc)
        return info
    err = (proc.stderr or proc.stdout or "").strip()
    if proc.returncode != 0:
        info["error"] = err[:400]
        info["permission_denied"] = "permission denied" in err.lower()
        return info
    info["ok"] = True
    return info


def require_docker() -> dict[str, Any]:
    access = docker_access()
    if not access["ok"]:
        raise DockerBlocked(
            "BLOCKED: experimental Grok container cannot start "
            f"({access.get('error') or 'docker unavailable'}). "
            "No host Grok fallback. No simulation batch."
        )
    return access


def compose_text() -> str:
    return COMPOSE.read_text()


def dockerfile_text() -> str:
    return DOCKERFILE.read_text()


def validate_spec() -> list[str]:
    """Static fail-closed checks. Does not need a live daemon."""
    errors: list[str] = []
    compose = compose_text()
    df = dockerfile_text()
    for snip in REQUIRED_COMPOSE_SNIPPETS:
        if snip not in compose:
            errors.append(f"compose missing {snip!r}")
    for line in compose.splitlines():
        stripped = line.strip()
        if stripped.startswith("source:"):
            for bad in FORBIDDEN_MOUNT_SOURCES:
                if bad in stripped:
                    errors.append(f"forbidden mount {bad}")
    if "privileged: true" in compose:
        errors.append("privileged true")
    if "network_mode: host" in compose or "pid: host" in compose:
        errors.append("host namespace")
    grok_block = _service_block(compose, "grok-operator")
    for line in grok_block.splitlines():
        stripped = line.split("#", 1)[0].strip()
        if stripped.startswith("extra_hosts"):
            errors.append("grok-operator extra_hosts")
        if "docker.sock" in stripped:
            errors.append("grok-operator docker.sock")
    if "USER 10001" not in df:
        errors.append("dockerfile not USER 10001")
    if "auth.json" in df.lower():
        errors.append("dockerfile mentions auth.json")
    if "COPY grok " in df:
        errors.append("CLI binaries must not be bundled in images")
    return errors


def _service_block(compose: str, name: str) -> str:
    lines = compose.splitlines()
    out: list[str] = []
    capture = False
    for line in lines:
        if line.startswith("  ") and not line.startswith("    ") and line.strip().endswith(":"):
            capture = line.strip() == f"{name}:"
        if capture:
            out.append(line)
    return "\n".join(out)


def historical_host_exposure() -> list[str]:
    return ["Host-only offline qualification is not an OS isolation boundary."]


def remaining_limitations() -> list[str]:
    return ["Subscription authentication is readable by the CLI process inside its private scratch.",
            "A current Docker Engine supporting isolated bridge gateways is required."]


def study_container_argv_fragment() -> list[str]:
    return ["--study-container-grok"]


def launch_or_block(*, require_live: bool = True) -> dict[str, Any]:
    spec_errors = validate_spec()
    if spec_errors:
        raise DockerBlocked("BLOCKED: container spec invalid: " + "; ".join(spec_errors))
    access = docker_access()
    if require_live and not access["ok"]:
        raise DockerBlocked(
            "BLOCKED: docker.sock not usable by this UID "
            f"(mode={access.get('sock_mode')} error={access.get('error')!r}). "
            "No host fallback. No simulation batch."
        )
    return {"access": access, "spec_errors": spec_errors}


def docker_is_snap() -> bool:
    which = shutil.which("docker") or ""
    return "snap" in which or Path("/snap/bin/docker").is_file()


def no_new_privileges_usable() -> bool:
    """Snap docker 29.x on this host EPERMs every exec with the flag (measured)."""
    return not docker_is_snap()


def nnp_security_args() -> list[str]:
    """Flag is required. Do not omit it because snap docker EPERMs exec."""
    return ["--security-opt", "no-new-privileges:true"]


def operator_security_argv(
    *,
    name: str,
    station: Path,
    scratch: Path,
    network: str,
    image: str = IMAGE,
    entrypoint: str = "/bin/sleep",
    args: list[str] | None = None,
    broker_host: str = "eclss-broker",
    detach: bool = True,
    no_new_privileges: bool | None = None,
) -> list[str]:
    """Inspectable docker run argv. Tests assert flags without a daemon."""
    if no_new_privileges is None:
        no_new_privileges = True
    cmd = [
        "docker",
        "run",
        "--rm",
    ]
    if detach:
        cmd.append("-d")
    cmd.extend(
        [
            "--name",
            name,
            "--user",
            OPERATOR_UID,
            "--read-only",
            "--cap-drop",
            "ALL",
            "--network",
            network,
            "--pids-limit",
            "256",
            "--memory",
            "4g",
            "--tmpfs",
            f"/tmp:uid={OPERATOR_UID.split(':')[0]},gid={OPERATOR_UID.split(':')[1]},mode=700",
        ]
    )
    if no_new_privileges:
        cmd.extend(["--security-opt", "no-new-privileges:true"])
    cmd.extend(
        [
            "--mount",
            f"type=bind,src={station},dst={STATION_INSIDE},readonly",
            "--mount",
            f"type=bind,src={scratch},dst=/home/watch/scratch",
            "--env",
            "HOME=/home/watch",
            "--env",
            f"GROK_HOME={HOME_INSIDE}",
            "--env",
            f"ECLSS_BROKER={broker_host}:9377",
            "--env",
            "USER=watch",
            "--entrypoint",
            entrypoint,
            image,
        ]
    )
    binary = os.environ.get("STUDY_FAKE_GROK") or os.environ.get("GROK_BIN")
    if not binary or not Path(binary).is_file():
        raise DockerBlocked("Explicit CLI executable is required")
    mount = ["--mount", f"type=bind,src={Path(binary).resolve()},dst={GROK_INSIDE},readonly"]
    image_index = cmd.index(image)
    cmd[image_index:image_index] = mount
    cmd.extend(args or ["infinity"])
    return cmd


def inspect_operator_argv(argv: list[str]) -> list[str]:
    """Return problems in a docker run argv (host fallback / privilege)."""
    blob = " ".join(argv)
    errors: list[str] = []
    if "docker.sock" in blob:
        errors.append("docker.sock")
    if "--privileged" in argv:
        errors.append("privileged")
    if "--network" in argv and "host" in argv[argv.index("--network") + 1 : argv.index("--network") + 2]:
        errors.append("host network")
    if "--pid" in argv and "host" in argv:
        errors.append("host pid")
    if "BIOSIM_URL" in blob or "XAI_API_KEY" in blob or "GROK_API_KEY" in blob:
        errors.append("secret env")
    for i, item in enumerate(argv):
        if item != "--mount" or i + 1 >= len(argv):
            continue
        spec = argv[i + 1]
        src = ""
        for part in spec.split(","):
            if part.startswith("src="):
                src = part[4:]
        if src.rstrip("/") == str(ROOT):
            errors.append("wrapper tree bind")
        if src.endswith("auth.json") or src.endswith("docker.sock"):
            errors.append(f"secret mount {src}")
        if "/hijack_scripts/" in src or src.endswith("/quarantine"):
            errors.append("packet/quarantine mount")
    for flag in ("--read-only", "--cap-drop", "--user"):
        if flag not in argv:
            errors.append(f"missing {flag}")
    if OPERATOR_UID not in argv:
        errors.append("missing nonroot uid")
    if "no-new-privileges:true" not in argv:
        errors.append("missing no-new-privileges")
    return errors


def write_container_mcp_config(grok_home: Path, *, broker_host: str = "eclss-broker") -> Path:
    """Operator-readable config: eclss-bridge only. No BIOSIM_URL, no auth copy."""
    grok_home.mkdir(parents=True, exist_ok=True)
    if (grok_home / "auth.json").exists():
        (grok_home / "auth.json").unlink()
    broker = f"{broker_host}:9377"
    body = (
        "[compat.claude]\n"
        "skills = false\n"
        "rules = false\n"
        "agents = false\n"
        "mcps = false\n"
        "hooks = false\n"
        "sessions = false\n"
        "[compat.cursor]\n"
        "skills = false\n"
        "rules = false\n"
        "agents = false\n"
        "mcps = false\n"
        "hooks = false\n"
        "sessions = false\n"
        "[compat.codex]\n"
        "sessions = false\n"
        "[cli]\n"
        "auto_update = false\n"
        '[mcp_servers.eclss]\n'
        'command = "/usr/local/bin/eclss-bridge"\n'
        "enabled = true\n"
        "[mcp_servers.eclss.env]\n"
        f"ECLSS_BROKER = {json.dumps(broker)}\n"
        "[skills]\n"
        'disabled = ["f029-cell-read"]\n'
    )
    path = grok_home / "config.toml"
    path.write_text(body)
    return path


def remap_grok_cmd_to_container(cmd: list[str], *, host_workspace: Path, host_home: Path) -> list[str]:
    out: list[str] = []
    for item in cmd:
        if item == str(host_workspace) or item == str(host_workspace.resolve()):
            out.append(STATION_INSIDE)
        elif item == str(host_home) or item.startswith(str(host_home) + os.sep):
            out.append(item.replace(str(host_home), HOME_INSIDE, 1))
        elif item.endswith("/grok") or item.endswith("/fake_grok.py") or Path(item).name == "grok":
            out.append(GROK_INSIDE)
        else:
            out.append(item)
    if out:
        out[0] = GROK_INSIDE
    return out


def episode_paths(episode_id: str) -> dict[str, Path]:
    root = STUDY_EPISODES / episode_id
    return {
        "root": root,
        "station": root / "station",
        "scratch": root / "scratch",
        "broker": root / "broker",
        "logs": root / "logs",
    }


def prepare_episode_dirs(episode_id: str, station_src: Path) -> dict[str, Path]:
    paths = episode_paths(episode_id)
    for key in ("root", "station", "scratch", "broker", "logs"):
        paths[key].mkdir(parents=True, exist_ok=True)
    for name in ("SOUL.md", "STATION.md", "AGENTS.md", "CLAUDE.md", "README.md"):
        src = station_src / name
        if src.is_file() and src.resolve() != (paths["station"] / name).resolve():
            shutil.copy2(src, paths["station"] / name)
    skill_src = station_src / "skills" / "station-eclss" / "SKILL.md"
    if skill_src.is_file():
        dest = paths["station"] / "skills" / "station-eclss"
        dest.mkdir(parents=True, exist_ok=True)
        if skill_src.resolve() != (dest / "SKILL.md").resolve():
            shutil.copy2(skill_src, dest / "SKILL.md")
    grok_home = paths["scratch"] / "grok-home"
    grok_home.mkdir(parents=True, exist_ok=True)
    write_container_mcp_config(grok_home, broker_host=f"eclss-broker-{episode_id[:12]}")
    if os.geteuid() == 0:
        for item in [paths["scratch"], *paths["scratch"].rglob("*")]:
            os.chown(item, 10001, 10001)
    paths["scratch"].chmod(0o700)
    paths["broker"].chmod(0o755)
    return paths


def iptables_plan(*, operator_cidr: str, plant_port: int) -> list[str]:
    """Host-side plan. Not applied without docker/CAP_NET_ADMIN."""
    return [
        f"# drop operator -> host except nothing published on 127.0.0.1 (plant {plant_port})",
        f"# operator cidr {operator_cidr} must not reach RFC1918, metadata, or other episodes",
        "iptables -N SATML-STUDY 2>/dev/null || true",
        "iptables -C DOCKER-USER -j SATML-STUDY 2>/dev/null || iptables -I DOCKER-USER -j SATML-STUDY",
        f"iptables -A SATML-STUDY -s {operator_cidr} -d 169.254.169.254 -j DROP",
        f"iptables -A SATML-STUDY -s {operator_cidr} -d 10.0.0.0/8 -j DROP",
        f"iptables -A SATML-STUDY -s {operator_cidr} -d 192.168.0.0/16 -j DROP",
        f"iptables -A SATML-STUDY -s {operator_cidr} -p tcp --dport {plant_port} -j DROP",
    ]


def set_active(containment: "StudyContainment | None") -> None:
    global _ACTIVE
    _ACTIVE = containment


def active() -> "StudyContainment | None":
    return _ACTIVE


class StudyContainment:
    """Trusted-controller session: host broker + operator container."""

    def __init__(
        self,
        *,
        episode_id: str,
        station_src: Path,
        plant_url: str,
        grok_timeout: int = 180,
        room_path: Path | None = None,
        mode: str = "advanced",
        transcript_path: Path | None = None,
        model: str = "grok-4.6",
    ) -> None:
        from biosim_operator.grok_harness import NATIVE_SUBSCRIPTION_MODELS

        if os.environ.get('STUDY_FAKE_GROK'):
            self._native_subscription = False
            self._offline = True
        else:
            from biosim_operator.provider_config import load_provider, require_live
            require_live()
            self._native_subscription = load_provider(model)['kind'] == 'subscription'
            self._offline = False
        self.model = model
        self.episode_id = episode_id
        self.station_src = Path(station_src)
        self.plant_url = plant_url
        self.grok_timeout = grok_timeout
        self.room_path = Path(room_path) if room_path else None
        self.mode = mode
        self.transcript_path = Path(transcript_path) if transcript_path else None
        self.paths = episode_paths(episode_id)
        self.network = f"satml-op-{episode_id[:12]}"
        self.egress_network = f"satml-eg-{episode_id[:12]}"
        self.operator_name = f"satml-grok-{episode_id[:12]}"
        self.relay_name = f"eclss-broker-{episode_id[:12]}"
        self.proxy_name = f"model-proxy-{episode_id[:12]}"
        self.operator_id: str | None = None
        self.relay_id: str | None = None
        self.proxy_id: str | None = None
        self._broker_proc: subprocess.Popen[str] | None = None
        self._proxy_thread: threading.Thread | None = None
        self._proxy_httpd: Any = None
        self._auth_copy: Path | None = None
        self._route_proc: subprocess.Popen | None = None

    def start(self) -> dict[str, Any]:
        launch_or_block(require_live=True)
        ensure_operator_image()
        prepare_episode_dirs(self.episode_id, self.station_src)
        try:
            self._start_host_broker()
            self._docker([
                "network", "create", "--internal", "--opt",
                "com.docker.network.bridge.gateway_mode_ipv4=isolated", self.network,
            ])
            self._docker(["network", "create", self.egress_network])
            self._start_relay()
            if self._native_subscription:
                self._start_proxy_container()
            elif not self._offline:
                self._start_model_route()
            self._start_operator()
            return self.inspect_namespaces()
        except BaseException:
            self.stop()
            raise

    def stop(self) -> None:
        if self._auth_copy is not None:
            self._auth_copy.unlink(missing_ok=True)
            self._auth_copy = None
        for cid in (self.operator_id, self.relay_id, self.proxy_id):
            if cid:
                subprocess.run(["docker", "rm", "-f", cid], capture_output=True)
        subprocess.run(["docker", "network", "rm", self.network], capture_output=True)
        subprocess.run(["docker", "network", "rm", self.egress_network], capture_output=True)
        if self._broker_proc is not None:
            self._broker_proc.terminate()
            try:
                self._broker_proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._broker_proc.kill()
            self._broker_proc = None
        if self._route_proc is not None:
            self._route_proc.terminate()
            try:
                self._route_proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._route_proc.kill()
                self._route_proc.wait()
            self._route_proc = None
        self.operator_id = None
        self.relay_id = None
        self.proxy_id = None

    def run_grok(
        self,
        cmd: list[str],
        *,
        timeout: int,
        host_workspace: Path | None = None,
        host_home: Path | None = None,
    ) -> subprocess.CompletedProcess[str]:
        if not self.operator_id:
            raise DockerBlocked("BLOCKED: operator container is not running")
        if "--tools" not in cmd or cmd[cmd.index("--tools") + 1] != "":
            raise DockerBlocked("Native credential use requires the verified MCP-only tool surface")
        if self._native_subscription and self._auth_copy is None:
            from biosim_operator.provider_config import load_provider
            source = Path(load_provider(self.model).get("auth_file", ""))
            if not source.is_file():
                raise DockerBlocked("Native subscription credentials unavailable; no API-key fallback")
            self._auth_copy = self.paths["scratch"] / "grok-home" / "auth.json"
            shutil.copyfile(source, self._auth_copy)
            if os.geteuid() == 0:
                os.chown(self._auth_copy, *map(int, OPERATOR_UID.split(":")))
            self._auth_copy.chmod(0o600)
        inner = remap_grok_cmd_to_container(
            cmd,
            host_workspace=host_workspace or self.paths["station"],
            host_home=host_home or (self.paths["scratch"] / "grok-home"),
        )
        exec_cmd = [
            "docker",
            "exec",
            "-u",
            OPERATOR_UID,
            "-w",
            STATION_INSIDE,
            "-e",
            f"GROK_HOME={HOME_INSIDE}",
            "-e",
            "HOME=/home/watch",
            "-e",
            f"ECLSS_BROKER={self.relay_name}:9377",
            "-e", f"HTTPS_PROXY=http://{self.proxy_name}:8080",
            "-e", f"HTTP_PROXY=http://{self.proxy_name}:8080",
            "-e", f"NO_PROXY={self.relay_name},{self.proxy_name}",
            "-e", f"GROK_DISABLE_API_KEY_AUTH={'1' if self._native_subscription else '0'}",
            self.operator_name,
            *inner,
        ]
        if self._offline:
            index = exec_cmd.index(self.operator_name)
            extra = []
            for key in ("FAKE_CAP_WATCH", "FAKE_FAILURE_WATCH", "FAKE_PARTIAL_DEATH", "FAKE_FATAL", "FAKE_HANG_WATCH"):
                if key in os.environ:
                    extra.extend(["-e", key + "=" + os.environ[key]])
            exec_cmd[index:index] = extra
        diagnostics = os.environ.get("STUDY_ROUTE_DIAGNOSTICS")
        sys.path.insert(0, str(ROOT / "scripts/study"))
        from recovery_diagnostics import run_owned_client
        return run_owned_client(exec_cmd, container_id=self.operator_id, timeout=timeout,
                                diagnostics=Path(diagnostics) if diagnostics else None,
                                quiesce=self.quiesce_operator)

    def quiesce_operator(self) -> None:
        """Stop all panel senders, then wait behind already accepted broker work."""
        for attribute in ("operator_id", "relay_id"):
            cid = getattr(self, attribute)
            if cid:
                self._docker(["rm", "-f", cid])
                setattr(self, attribute, None)
        if getattr(self, "_panel_quiescent", False):
            return
        if self._broker_proc is None or self._broker_proc.poll() is not None:
            raise DockerBlocked("Cannot establish terminal panel state: broker unavailable")
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
            connection.settimeout(self.grok_timeout)
            connection.connect(str(self.paths["broker"] / "eclss.sock"))
            connection.sendall(b'{"op":"barrier"}\n')
            with connection.makefile("rb") as stream:
                reply = json.loads(stream.readline())
        if reply != {"settled": True}:
            raise DockerBlocked("Panel quiescence acknowledgement missing")
        self._panel_quiescent = True
        if self.transcript_path:
            with self.transcript_path.open("a") as stream:
                stream.write(json.dumps({"event": "operator_quiescent", "panel_settled": True}) + "\n")


    def inspect_namespaces(self) -> dict[str, Any]:
        info: dict[str, Any] = {
            "operator_name": self.operator_name,
            "network": self.network,
            "plant_url_in_operator_env": False,
        }
        if not docker_access()["ok"]:
            info["blocked"] = True
            return info
        inspect = subprocess.run(
            ["docker", "inspect", self.operator_name, "--format", "{{json .}}"],
            capture_output=True,
            text=True,
            timeout=15,
        )
        if inspect.returncode != 0:
            info["error"] = inspect.stderr[-400:]
            return info
        try:
            payload = json.loads(inspect.stdout)
        except json.JSONDecodeError:
            info["error"] = "inspect json"
            return info
        host_cfg = payload.get("HostConfig") or {}
        mounts = payload.get("Mounts") or []
        ns = (payload.get("NetworkSettings") or {}).get("Networks") or {}
        env = payload.get("Config", {}).get("Env") or []
        info["privileged"] = bool(host_cfg.get("Privileged"))
        info["cap_add"] = host_cfg.get("CapAdd")
        info["readonly"] = bool(host_cfg.get("ReadonlyRootfs"))
        info["networks"] = list(ns)
        info["mounts"] = [
            {
                "source": m.get("Source"),
                "destination": m.get("Destination"),
                "rw": m.get("RW"),
            }
            for m in mounts
        ]
        info["env_sensitive"] = [
            e.split("=", 1)[0]
            for e in env
            if any(s in e for s in ("BIOSIM_URL", "XAI_API_KEY", "GROK_API_KEY", "AUTH"))
        ]
        pid = subprocess.run(
            ["docker", "exec", self.operator_name, "python3", "-c", "import os; print(os.getpid())"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        host_pid = os.getpid()
        info["container_reported_pid"] = (pid.stdout or "").strip()
        info["host_controller_pid"] = host_pid
        info["pid_namespace_differs"] = (pid.stdout or "").strip() != str(host_pid)
        return info

    def _docker(self, args: list[str]) -> subprocess.CompletedProcess[str]:
        proc = subprocess.run(["docker", *args], capture_output=True, text=True, timeout=120)
        if proc.returncode != 0:
            raise DockerBlocked(f"BLOCKED: docker {' '.join(args[:4])} failed: {(proc.stderr or '')[-400:]}")
        return proc

    def _start_host_broker(self) -> None:
        sock = self.paths["broker"] / "eclss.sock"
        env = os.environ.copy()
        env["ECLSS_BROKER_SOCK"] = str(sock)
        env["BIOSIM_URL"] = self.plant_url
        env["ECLSS_URL"] = self.plant_url
        env["PYTHONPATH"] = str(ROOT / "src")
        env["BIOSIM_MODE"] = self.mode
        env["ECLSS_MODE"] = self.mode
        if self.room_path is not None:
            env["BIOSIM_ROOM_STATE"] = str(self.room_path)
            env["ECLSS_STATE"] = str(self.room_path)
        if self.transcript_path is not None:
            env["BIOSIM_TRANSCRIPT"] = str(self.transcript_path)
            env["ECLSS_TRANSCRIPT"] = str(self.transcript_path)
        with (self.paths["logs"] / "broker.log").open("ab") as log:
            self._broker_proc = subprocess.Popen(
                [os.environ.get("ECLSS_BROKER_PYTHON", sys.executable), str(ROOT / "scripts" / "study" / "eclss_broker.py")],
                env=env,
                stdout=log,
                stderr=log,
            )
        deadline = time.time() + 8
        while time.time() < deadline:
            if sock.exists():
                return
            time.sleep(0.05)
        raise DockerBlocked("BLOCKED: host eclss broker socket did not appear")

    def _start_relay(self) -> None:
        proc = subprocess.run(
            [
                "docker",
                "run",
                "-d",
                "--rm",
                "--name",
                self.relay_name,
                "--user",
                "65534:65534",
                "--cap-drop",
                "ALL",
                *nnp_security_args(),
                "--network",
                self.network,
                "--read-only",
                "--tmpfs",
                "/tmp",
                "--mount",
                f"type=bind,src={self.paths['broker']},dst=/run/broker",
                "--env",
                "RELAY_UNIX=/run/broker/eclss.sock",
                "--entrypoint",
                "python3",
                IMAGE,
                "/usr/local/bin/unix-tcp-relay",
            ],
            capture_output=True,
            text=True,
            timeout=60,
        )
        if proc.returncode != 0:
            raise DockerBlocked(f"BLOCKED: eclss relay failed: {(proc.stderr or '')[-400:]}")
        self.relay_id = proc.stdout.strip()

    def _start_model_route(self) -> None:
        from biosim_operator.provider_config import load_provider, model_toml
        provider = load_provider(self.model)
        route_dir = self.paths['root'] / 'model-route'
        route_dir.mkdir(mode=0o755)
        sock = route_dir / 'route.sock'
        env = dict(os.environ, STUDY_ROUTE_MODEL=self.model, STUDY_ROUTE_SOCKET=str(sock))
        with (self.paths['logs'] / 'model-route.log').open('ab') as log:
            self._route_proc = subprocess.Popen(
                [sys.executable, str(ROOT / 'scripts/study/route_broker.py')], env=env, stdout=log, stderr=log)
        deadline = time.monotonic() + 8
        while not sock.exists():
            if self._route_proc.poll() is not None or time.monotonic() >= deadline:
                raise DockerBlocked('Model route socket unavailable')
            time.sleep(.05)
        proc = self._docker(['run', '-d', '--rm', '--name', self.proxy_name,
            '--user', '65534:65534', '--cap-drop', 'ALL', *nnp_security_args(),
            '--network', self.network, '--read-only',
            '--mount', f'type=bind,src={route_dir},dst=/run/route,readonly',
            '--env', 'RELAY_UNIX=/run/route/route.sock', '--env', 'RELAY_LISTEN_PORT=8080',
            '--entrypoint', 'python3', IMAGE, '/usr/local/bin/unix-tcp-relay'])
        self.proxy_id = proc.stdout.strip()
        config = self.paths['scratch'] / 'grok-home/config.toml'
        with config.open('a') as stream:
            stream.write(model_toml(self.model, provider, f'http://{self.proxy_name}:8080/v1'))

    def _start_proxy_container(self) -> None:
        mounts = [
            "--mount",
            f"type=bind,src={ROOT / 'scripts' / 'study' / 'connect_proxy.py'},dst=/opt/connect_proxy.py,readonly",
        ]
        env = []
        proc = subprocess.run(
            [
                "docker",
                "run",
                "-d",
                "--rm",
                "--name",
                self.proxy_name,
                "--user",
                "65534:65534",
                "--cap-drop",
                "ALL",
                *nnp_security_args(),
                "--network",
                self.network,
                "--read-only",
                "--tmpfs",
                "/tmp",
                *mounts,
                *env,
                "--entrypoint",
                "python3",
                IMAGE,
                "/opt/connect_proxy.py",
            ],
            capture_output=True,
            text=True,
            timeout=60,
        )
        if proc.returncode != 0:
            raise DockerBlocked(f"BLOCKED: model-proxy failed: {(proc.stderr or '')[-400:]}")
        self.proxy_id = proc.stdout.strip()
        self._docker(["network", "connect", self.egress_network, self.proxy_name])

    def _start_operator(self) -> None:
        argv = operator_security_argv(
            name=self.operator_name,
            station=self.paths["station"],
            scratch=self.paths["scratch"],
            network=self.network,
            broker_host=self.relay_name,
        )
        problems = inspect_operator_argv(argv)
        if problems:
            raise DockerBlocked("BLOCKED: operator argv failed spec: " + "; ".join(problems))
        proc = subprocess.run(argv, capture_output=True, text=True, timeout=60)
        if proc.returncode != 0:
            raise DockerBlocked(f"BLOCKED: operator container failed: {(proc.stderr or '')[-400:]}")
        self.operator_id = proc.stdout.strip()

    def ensure_image(self) -> None:
        ensure_operator_image()


def ensure_operator_image() -> None:
    require_docker()
    inspect = subprocess.run(["docker", "image", "inspect", IMAGE], capture_output=True)
    if inspect.returncode:
        subprocess.run(["docker", "build", "-f", str(DOCKERFILE), "-t", IMAGE, str(DOCKERFILE.parent)], check=True)


def run_grok_in_container(
    cmd: list[str],
    *,
    timeout: int,
    host_workspace: Path | None = None,
    host_home: Path | None = None,
) -> subprocess.CompletedProcess[str]:
    session = active()
    if session is None:
        raise DockerBlocked(
            "BLOCKED: --study-container-grok has no active containment session. "
            "No host Grok fallback."
        )
    return session.run_grok(
        cmd, timeout=timeout, host_workspace=host_workspace, host_home=host_home
    )


def run_adversary_probes_or_block(*, episode_id: str = "probe") -> dict[str, Any]:
    """Real-container probes as uid 10001. Raises DockerBlocked without docker."""
    launch_or_block(require_live=True)
    ensure_operator_image()
    host_secret = HOST_CANARY_SECRET
    host_auth = HOST_CANARY_AUTH
    sibling = STUDY_EPISODES / "sibling" / "station"
    sibling.mkdir(parents=True, exist_ok=True)
    host_secret.write_text("CANARY_SECRET_NOT_A_REAL_CREDENTIAL\n")
    host_auth.write_text('{"canary": true, "not_real": true}\n')
    (sibling / "SOUL.md").write_text("sibling-canary\n")
    station_src = Path(tempfile.mkdtemp(prefix="satml-probe-station-"))
    (station_src / "SOUL.md").write_text("probe-soul\n")
    (station_src / "STATION.md").write_text("probe-station\n")
    (station_src / "AGENTS.md").write_text("probe-agents\n")
    containment = StudyContainment(
        episode_id=episode_id,
        station_src=station_src,
        plant_url="http://127.0.0.1:9",
    )
    try:
        prepare_episode_dirs(episode_id, station_src)
        require_docker()
        subprocess.run(["docker", "rm", "-f", containment.operator_name], capture_output=True)
        subprocess.run(["docker", "network", "rm", containment.network], capture_output=True)
        containment._docker(["network", "create", "--internal", containment.network])
        argv = operator_security_argv(
            name=containment.operator_name,
            station=containment.paths["station"],
            scratch=containment.paths["scratch"],
            network=containment.network,
            entrypoint="python3",
            args=["/probe.py"],
            broker_host=containment.relay_name,
            detach=False,
        )
        insert_at = argv.index(IMAGE)
        argv[insert_at:insert_at] = [
            "--mount",
            f"type=bind,src={ROOT / 'docker' / 'study' / 'adversary_probe.py'},dst=/probe.py,readonly",
            "--env",
            f"SATML_CANARY_SIBLING={sibling / 'SOUL.md'}",
        ]
        problems = inspect_operator_argv(argv)
        if problems:
            raise DockerBlocked("probe argv: " + "; ".join(problems))
        proc = subprocess.run(argv, capture_output=True, text=True, timeout=60)
        report: dict[str, Any]
        try:
            report = json.loads(proc.stdout or "{}")
        except json.JSONDecodeError:
            report = {"raw": proc.stdout, "stderr": proc.stderr, "returncode": proc.returncode}
        report["returncode"] = proc.returncode
        report["stderr_tail"] = (proc.stderr or "")[-400:]
        return report
    finally:
        subprocess.run(["docker", "rm", "-f", containment.operator_name], capture_output=True)
        subprocess.run(["docker", "network", "rm", containment.network], capture_output=True)
        shutil.rmtree(station_src, ignore_errors=True)
        try:
            host_secret.unlink()
            host_auth.unlink()
        except OSError:
            pass


def allocate_loopback_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])

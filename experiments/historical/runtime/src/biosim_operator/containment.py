"""Two-container station: plant JVM + watchstander console.

The operator process runs inside ``farside-console``. It does not see
the host home directory or this wrapper tree. The driver stays on the
host and talks to the plant at 127.0.0.1:8029; the panel inside talks
to hostname ``plant``.
"""

from __future__ import annotations

from pathlib import Path as _ArchivePath
import sys as _archive_sys
_archive_sys.path.insert(0, str(next(p for p in _ArchivePath(__file__).resolve().parents if (p / "archive_gate.py").is_file())))
from archive_gate import require_enabled, path as _archive_path, setting as _archive_setting, runtime_root as _archive_root
require_enabled()


import os
import shutil
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
COMPOSE_FILE = ROOT / "docker-compose.yml"
PROJECT = "farside"
CONSOLE_IMAGE = "farside-console:watch"
PLANT = "farside-plant"
HOST_PLANT_URL = _archive_setting('endpoint_004')
INSIDE_PLANT_URL = _archive_setting('endpoint_005')
# Host bind source. Snap Docker cannot mkdir under /opt. Each cell mounts
# ONE watch directory at /opt/farside/watches (no sibling W-* listing).
HOST_WATCHES = ROOT / ".docker-watches"
CONTAINER_WATCHES = Path("/opt/farside/watches")
PLANT_WATCH = "/opt/farside/bin/plant-watch"
AGENT_BIN = "agent"
EMPTY_PLUGINS = "/opt/farside/empty-plugins"
SEAT_ENV = "FARSIDE_SEAT"
NETWORK = f"{PROJECT}_default"

WATCH_ENV = {
    "HOME": "/home/watch",
    "USER": "watch",
    "LOGNAME": "watch",
    "XDG_CONFIG_HOME": "/home/watch/.config",
    "XDG_CACHE_HOME": "/home/watch/.cache",
    "XDG_DATA_HOME": "/home/watch/.local/share",
    "TMPDIR": "/tmp",
}


def enabled() -> bool:
    raw = os.environ.get("FARSIDE_DOCKER", "").strip().lower()
    return raw in {"1", "true", "yes", "on"}


def host_watches() -> Path:
    override = os.environ.get("FARSIDE_DOCKER_WATCHES", "").strip()
    path = Path(override) if override else HOST_WATCHES
    path.mkdir(parents=True, exist_ok=True)
    return path


def host_workspace(watch_id: str) -> Path:
    return host_watches() / watch_id


def inside_workspace(path: Path) -> Path:
    """In-container workspace. One seating, no sibling watch ids."""
    return CONTAINER_WATCHES


def seat_name(watch_id: str) -> str:
    slug = "".join(ch.lower() if ch.isalnum() else "-" for ch in watch_id).strip("-")
    return f"farside-seat-{slug}"


def current_seat() -> str:
    name = os.environ.get(SEAT_ENV, "").strip()
    if not name:
        raise RuntimeError(f"{SEAT_ENV} unset; call start_seat() before docker exec")
    return name


def stage_watch_cli() -> Path:
    """Copy the host Cursor CLI into the compose context.

    Snap Docker's buildkit cannot send ``~/.local`` as an additional
    context (it arrives empty). Staging under the wrapper tree is readable.
    """
    src = watch_cli_home()
    dest = ROOT / ".docker-watch-cli"
    dest.mkdir(parents=True, exist_ok=True)
    rsync = subprocess.run(
        ["rsync", "-a", "--delete", f"{src}/", f"{dest}/"],
        capture_output=True,
        text=True,
    )
    if rsync.returncode != 0:
        import shutil

        if dest.exists():
            shutil.rmtree(dest)
        shutil.copytree(src, dest, symlinks=True)
    if not (dest / "cursor-agent").is_file() or not (dest / "node").is_file():
        raise FileNotFoundError(f"staged CLI missing cursor-agent/node under {dest}")
    return dest


def stage_auth() -> Path:
    """Copy Cursor auth into the compose context.

    Snap Docker rewrites ``$HOME/...`` bind sources into ``~/snap/docker/...``.
    Staging next to the compose file keeps the file a file (not a directory
    docker creates when the source is missing).
    """
    src = _archive_path('path_002')
    if not src.is_file():
        raise FileNotFoundError(f"missing Cursor auth at {src}")
    dest_dir = ROOT / ".docker-secrets"
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / "auth.json"
    if dest.exists() and dest.is_dir():
        shutil.rmtree(dest)
    shutil.copy2(src, dest)
    dest.chmod(0o600)
    return dest


def watch_cli_home() -> Path:
    override = os.environ.get("WATCH_CLI_HOME", "").strip()
    if override:
        return Path(override)
    found = None
    for name in ("cursor-agent", "agent"):
        which = subprocess.run(["which", name], capture_output=True, text=True)
        if which.returncode == 0 and which.stdout.strip():
            found = Path(which.stdout.strip())
            break
    if found is None:
        raise FileNotFoundError("cursor-agent is not on PATH; cannot build the console image")
    return Path(os.path.realpath(found)).parent


def plant_jar_dir() -> Path:
    override = os.environ.get("PLANT_JAR_DIR", "").strip()
    if override:
        return Path(override)
    return (
        _archive_path('path_003')
    )


def compose_env() -> dict[str, str]:
    env = os.environ.copy()
    env["WATCH_CLI_HOME"] = str(watch_cli_home())
    env["PLANT_JAR_DIR"] = str(plant_jar_dir())
    env["STATION_ROOT"] = str(ROOT)
    env["HOME"] = str(Path.home())
    return env


def _compose(argv: list[str], timeout: int = 600) -> subprocess.CompletedProcess[str]:
    cmd = ["docker", "compose", "-p", PROJECT, "-f", str(COMPOSE_FILE), *argv]
    proc = subprocess.run(
        cmd,
        cwd=str(ROOT),
        env=compose_env(),
        text=True,
        capture_output=True,
        timeout=timeout,
    )
    if proc.returncode != 0:
        blob = ((proc.stdout or "") + "\n" + (proc.stderr or "")).strip()
        raise RuntimeError(f"docker compose {' '.join(argv)} failed: {blob[-2000:]}")
    return proc


def plant_is_up(url: str = HOST_PLANT_URL, timeout: float = 1.5) -> bool:
    try:
        with urllib.request.urlopen(f"{url.rstrip('/')}/api/simulation", timeout=timeout) as resp:
            return 200 <= resp.status < 300
    except (urllib.error.URLError, TimeoutError, OSError):
        return False


def ensure_stack(wait_s: float = 90.0, *, recreate_plant: bool = False) -> None:
    """Build/start plant + console. Idempotent. Fails loud.

    A live plant holds BioSim sim_ids. ``--force-recreate`` wipes them.
    v16 Cursor + v17 Grok both landed on sim_id=1 because each episode
    called this and bounced the JVM. Default: if the plant already
    answers HTTP, leave it. Pass recreate_plant=True for a clean jar.
    """
    if not COMPOSE_FILE.is_file():
        raise FileNotFoundError(f"missing {COMPOSE_FILE}")
    jar = plant_jar_dir() / "biosim-2.0.0-jar-with-dependencies.jar"
    if not jar.is_file():
        raise FileNotFoundError(f"plant jar not at {jar}")
    host_watches()
    stage_auth()
    os.environ.setdefault("BIOSIM_URL", HOST_PLANT_URL)
    if plant_is_up() and not recreate_plant:
        return
    # Panel code is COPY'd into the image. Always rebuild console so a
    # host src/ fix (e.g. embedded commission beats) is what the seat runs.
    # The plant image COPY's the jar — a Fan.java rebuild is otherwise
    # invisible behind a still-running farside-plant.
    if not (ROOT / ".docker-watch-cli" / "node").is_file():
        stage_watch_cli()
    _compose(["build", "console"], timeout=600)
    _compose(["build", "plant"], timeout=300)
    _compose(["up", "-d", "--force-recreate", "plant"], timeout=120)
    subprocess.run(["docker", "rm", "-f", "farside-console"], capture_output=True)
    deadline = time.time() + wait_s
    last = ""
    while time.time() < deadline:
        if plant_is_up():
            return
        last = "plant HTTP not answering"
        time.sleep(0.5)
    raise RuntimeError(
        f"plant container did not answer {HOST_PLANT_URL} within {wait_s}s ({last})"
    )


def exec_console(
    argv: list[str],
    *,
    user: str = "watch",
    cwd: str | None = None,
    stdin: bytes | None = None,
    timeout: int = 60,
    extra_env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    cmd = ["docker", "exec", "-i", "-u", user]
    env_map = dict(WATCH_ENV) if user == "watch" else {}
    if extra_env:
        env_map.update(extra_env)
    for key, val in env_map.items():
        cmd.extend(["-e", f"{key}={val}"])
    if cwd:
        cmd.extend(["-w", cwd])
    cmd.append(current_seat())
    cmd.extend(argv)
    return subprocess.run(
        cmd,
        input=stdin.decode("utf-8") if isinstance(stdin, bytes) else stdin,
        text=True,
        capture_output=True,
        timeout=timeout,
    )


def exec_watch(
    argv: list[str],
    *,
    cwd: str | None = None,
    timeout: int = 180,
) -> subprocess.CompletedProcess[str]:
    return exec_console(argv, user="watch", cwd=cwd, timeout=timeout)


def plant_launch(
    watch_id: str,
    *,
    mode: str,
    url: str,
    state: Path | None = None,
) -> Path:
    blob = b"{}\n"
    if state is not None and Path(state).is_file():
        from biosim_operator.room_state import panel_bytes_for

        blob = panel_bytes_for(Path(state))
    proc = exec_console(
        [
            PLANT_WATCH,
            "--watch-id",
            watch_id,
            "--mode",
            mode,
            "--url",
            url or INSIDE_PLANT_URL,
            "--prefix",
            "/opt/farside",
        ],
        user="eclss",
        stdin=blob,
        timeout=30,
    )
    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout or "").strip()
        raise RuntimeError(f"plant-watch failed ({proc.returncode}): {err}")
    return Path("/opt/farside/var") / watch_id / "launch.json"


def push_state(watch_id: str, room_path: Path) -> None:
    src = Path(room_path)
    if not src.is_file():
        return
    from biosim_operator.room_state import panel_bytes_for

    proc = exec_console(
        [
            PLANT_WATCH,
            "--watch-id",
            watch_id,
            "--prefix",
            "/opt/farside",
            "--state-only",
        ],
        user="eclss",
        stdin=panel_bytes_for(src),
        timeout=30,
    )
    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout or "").strip()
        raise RuntimeError(f"plant-watch --state-only failed ({proc.returncode}): {err}")


def pull_state(watch_id: str, room_path: Path) -> None:
    proc = exec_console(
        [
            PLANT_WATCH,
            "--watch-id",
            watch_id,
            "--prefix",
            "/opt/farside",
            "--dump-state",
        ],
        user="eclss",
        timeout=30,
    )
    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout or "").strip()
        raise RuntimeError(f"plant-watch --dump-state failed ({proc.returncode}): {err}")
    from biosim_operator.room_state import merge_panel_into_host

    dest = Path(room_path)
    merge_panel_into_host(dest, (proc.stdout or "{}").encode())


def invoke_agent(
    argv: list[str],
    *,
    workspace: Path,
    timeout: int,
) -> subprocess.CompletedProcess[str]:
    inside = str(inside_workspace(workspace))
    return exec_watch([AGENT_BIN, *argv], cwd=inside, timeout=timeout)


def _seat_running(name: str) -> bool:
    proc = subprocess.run(
        ["docker", "inspect", "-f", "{{.State.Running}}", name],
        capture_output=True,
        text=True,
        timeout=15,
    )
    return proc.returncode == 0 and proc.stdout.strip() == "true"


def start_seat(watch_id: str, host_ws: Path) -> str:
    """One disposable console per cell. Mounts only this seating."""
    name = seat_name(watch_id)
    os.environ[SEAT_ENV] = name
    host_ws = Path(host_ws)
    host_ws.mkdir(parents=True, exist_ok=True)
    auth = stage_auth()
    subprocess.run(["docker", "rm", "-f", name], capture_output=True)
    cmd = [
        "docker",
        "run",
        "-d",
        "--name",
        name,
        "--hostname",
        "console",
        "--network",
        NETWORK,
        "-v",
        f"{host_ws.resolve()}:{CONTAINER_WATCHES}",
        "-v",
        f"{auth.resolve()}:/home/watch/.config/cursor/auth.json:ro",
        CONSOLE_IMAGE,
        "sleep",
        "infinity",
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    if proc.returncode != 0:
        raise RuntimeError(
            f"docker run {name} failed: {(proc.stderr or proc.stdout or '').strip()[-1500:]}"
        )
    deadline = time.time() + 20
    while time.time() < deadline:
        if _seat_running(name):
            _lock_cursor_plugins(name)
            return name
        time.sleep(0.2)
    raise RuntimeError(f"seat {name} did not start")


def _lock_cursor_plugins(name: str) -> None:
    """contributor's Cursor account would otherwise drop Gmail/Drive/provider_cloud into HOME.

    MCP attach is already eclss-only; this stops the plugin *tree* from
    existing for Glob/Read. Root-owned 700: watch cannot list names.
    """
    # User-level mcp.json is the same allowlist as the workspace: eclss only.
    # 444 root so the CLI cannot append Gmail/Drive from the logged-in account.
    script = (
        "mkdir -p /opt/farside/empty-plugins "
        "/home/watch/.cursor/plugins /home/watch/.cursor/skills-cursor; "
        "rm -rf /home/watch/.cursor/plugins/cache /home/watch/.cursor/plugins/* "
        "/home/watch/.cursor/skills-cursor/*; "
        "printf '%s\\n' "
        "'{\"mcpServers\":{\"eclss\":{\"command\":\"/usr/local/bin/eclss\"}}}' "
        "> /home/watch/.cursor/mcp.json; "
        "chown -R root:root /opt/farside/empty-plugins "
        "/home/watch/.cursor/plugins /home/watch/.cursor/skills-cursor "
        "/home/watch/.cursor/mcp.json; "
        "chmod 755 /opt/farside/empty-plugins; "
        "chmod 700 /home/watch/.cursor/plugins /home/watch/.cursor/skills-cursor; "
        "chmod 444 /home/watch/.cursor/mcp.json"
    )
    proc = subprocess.run(
        ["docker", "exec", "-u", "root", name, "sh", "-c", script],
        capture_output=True,
        text=True,
        timeout=20,
    )
    if proc.returncode != 0:
        raise RuntimeError(
            f"lock plugins failed: {(proc.stderr or proc.stdout or '').strip()[-800:]}"
        )


def harvest_seat(watch_id: str, dest: Path) -> None:
    """Copy Cursor HOME/tmp out of the seat onto the host driver tree.

    The agent never sees ``dest`` (it lives under runs/, not the workspace).
    """
    name = seat_name(watch_id)
    dest = Path(dest)
    dest.mkdir(parents=True, exist_ok=True)
    mapping = (
        ("/home/watch", dest / "cursor-home"),
        ("/tmp", dest / "cursor-tmp"),
        ("/opt/farside/var", dest / "panel-var"),
    )
    for src, target in mapping:
        target.mkdir(parents=True, exist_ok=True)
        proc = subprocess.run(
            ["docker", "cp", f"{name}:{src}/.", str(target)],
            capture_output=True,
            text=True,
            timeout=60,
        )
        if proc.returncode != 0:
            (dest / "harvest.log").open("a").write(
                f"{src}: {(proc.stderr or proc.stdout or '').strip()}\n"
            )


def stop_seat(watch_id: str, dest: Path | None = None) -> None:
    name = seat_name(watch_id)
    if dest is not None:
        try:
            harvest_seat(watch_id, dest)
        except Exception as exc:
            if dest is not None:
                Path(dest).mkdir(parents=True, exist_ok=True)
                (Path(dest) / "harvest.log").open("a").write(f"harvest: {exc}\n")
    subprocess.run(["docker", "rm", "-f", name], capture_output=True)
    if os.environ.get(SEAT_ENV) == name:
        os.environ.pop(SEAT_ENV, None)

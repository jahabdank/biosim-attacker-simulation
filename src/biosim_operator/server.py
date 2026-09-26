"""Start/stop a local stock BioSim JVM. Docker is preferred when the daemon is usable."""

from __future__ import annotations

import os
import socket
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlparse


DEFAULT_JAR = Path(__file__).resolve().parents[3] / "biosim" / "target" / "biosim-2.0.0-jar-with-dependencies.jar"


def _host_port_from_env() -> tuple[str, int]:
    """BIOSIM_URL takes precedence (e.g. http://127.0.0.1:8019); BIOSIM_PORT
    is a shorthand for changing just the port on the default host. Multiple
    concurrent episode drivers can point at one shared JVM (same URL) or at
    separate JVMs (distinct ports) — both are supported, see F-029 msg #457
    addendum."""
    url = os.environ.get("BIOSIM_URL", "").strip()
    if url:
        parsed = urlparse(url)
        if parsed.hostname:
            return parsed.hostname, parsed.port or 8009
    host = "127.0.0.1"
    port = 8009
    raw_port = os.environ.get("BIOSIM_PORT", "").strip()
    if raw_port:
        port = int(raw_port)
    return host, port


class BioSimServer:
    def __init__(
        self,
        jar: Path | None = None,
        host: str | None = None,
        port: int | None = None,
        write_ticks: bool = False,
    ):
        self.jar = Path(jar or os.environ.get("BIOSIM_JAR") or DEFAULT_JAR)
        self.externally_managed = jar is None and bool(os.environ.get("BIOSIM_URL") or os.environ.get("BIOSIM_PORT"))
        self.log_path = None
        env_host, env_port = _host_port_from_env()
        self.host = host or env_host
        self.port = port or env_port
        self.write_ticks = write_ticks
        self.proc: subprocess.Popen[str] | None = None

    @property
    def base_url(self) -> str:
        return f"http://{self.host}:{self.port}"

    def is_up(self) -> bool:
        try:
            with urllib.request.urlopen(f"{self.base_url}/api/simulation", timeout=1.5) as resp:
                return 200 <= resp.status < 300
        except (urllib.error.URLError, TimeoutError, OSError):
            return False

    def start(self, wait_s: float = 20.0, *, reuse_existing: bool = True) -> None:
        # An externally managed plant (BIOSIM_URL/BIOSIM_PORT already set,
        # e.g. the tool-server sidecar in docker-compose.yml) may still be
        # starting its own HTTP listener; poll instead of failing on the
        # first check.
        externally_managed = self.externally_managed
        deadline = time.time() + wait_s
        while True:
            if self.is_up():
                if reuse_existing:
                    return
                if self.proc is None:
                    raise RuntimeError(
                        f"listener already up on {self.base_url} and this BioSimServer does not own it"
                    )
                return
            if externally_managed and time.time() < deadline:
                time.sleep(0.25)
                continue
            break
        from biosim_operator.containment import enabled as docker_enabled
        from biosim_operator.containment import ensure_stack

        if docker_enabled():
            ensure_stack(wait_s=max(wait_s, 90.0))
            if self.is_up():
                return
            raise RuntimeError(
                f"plant container did not come up on {self.base_url} within {wait_s}s"
            )
        if externally_managed:
            raise RuntimeError(
                f"externally managed plant did not answer on {self.base_url} within {wait_s}s"
            )
        if not self.jar.is_file():
            raise FileNotFoundError(
                f"BioSim jar not found at {self.jar}. Build stock biosim with mvn -DskipTests package."
            )
        if _port_busy(self.host, self.port):
            raise RuntimeError(f"port {self.port} is busy but /api/simulation is not answering")
        args = [
            "java",
            "-jar",
            str(self.jar),
            "--host",
            self.host,
            "--port",
            str(self.port),
            f"--writeTicks={'true' if self.write_ticks else 'false'}",
        ]
        log_f = tempfile.NamedTemporaryFile(prefix=f"biosim-{self.port}-", suffix=".log", delete=False)
        log_path = Path(log_f.name)
        self.log_path = log_path
        try:
            self.proc = subprocess.Popen(
                args,
                cwd=str(self.jar.parent.parent),
                stdout=log_f,
                stderr=subprocess.STDOUT,
                text=True,
            )
        finally:
            log_f.close()
        deadline = time.time() + wait_s
        while time.time() < deadline:
            if self.proc.poll() is not None:
                raise RuntimeError(f"BioSim exited {self.proc.returncode}; see {log_path}")
            if self.is_up():
                return
            time.sleep(0.25)
        raise RuntimeError(f"BioSim did not come up on {self.base_url} within {wait_s}s")

    def stop(self) -> None:
        if self.proc is None:
            return
        self.proc.terminate()
        try:
            self.proc.wait(timeout=8)
        except subprocess.TimeoutExpired:
            self.proc.kill()
            self.proc.wait()
        self.proc = None
        if self.log_path:
            self.log_path.unlink(missing_ok=True)


def allocate_free_port(host: str = "127.0.0.1") -> int:
    """Bind :0, read the port, close. Caller must start the owner immediately."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind((host, 0))
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        return int(sock.getsockname()[1])


def _port_busy(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.3)
        return sock.connect_ex((host, port)) == 0

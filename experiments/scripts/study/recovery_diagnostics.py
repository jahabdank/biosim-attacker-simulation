"""Sanitized route checks shared by the recovery controller and owned client."""
from pathlib import Path
import subprocess
import time


def failure_reason(path: Path, *, active: bool) -> str | None:
    import json
    def read_events(path, *, active):
        if active and not path.exists():
            return []
        text = path.read_text()
        lines = text.splitlines()
        if active and text and not text.endswith("\n"):
            lines = lines[:-1]
        return [json.loads(line) for line in lines if line.strip()]
    try:
        events = read_events(path, active=active)
        for event in events:
            status = event.get("status", 0)
            if status == 429:
                return "quota"
            if event.get("event") in {"transport_error", "stream_error", "route_error"} or status >= 400:
                return "technical_failure"
    except (OSError, ValueError, TypeError, AttributeError):
        return "diagnostic_parse_failure"
    return None


def run_owned_client(command, *, container_id, timeout, diagnostics=None, quiesce):
    """Quiesce daemon-owned execution and panel calls before returning failure evidence."""
    started = time.monotonic()
    with subprocess.Popen(command, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE) as child:
        reason = None
        try:
            while True:
                try:
                    stdout, stderr = child.communicate(timeout=0.25)
                    reason = failure_reason(diagnostics, active=False) if diagnostics else None
                    if time.monotonic() - started >= timeout:
                        reason = "watch_timeout"
                    if reason:
                        quiesce()
                    if reason == "watch_timeout":
                        raise subprocess.TimeoutExpired(command, timeout, output=stdout, stderr=stderr)
                    return subprocess.CompletedProcess(command, 2 if reason else child.returncode, stdout, stderr)
                except subprocess.TimeoutExpired:
                    reason = failure_reason(diagnostics, active=True) if diagnostics else None
                    if time.monotonic() - started >= timeout:
                        reason = "watch_timeout"
                    if reason:
                        quiesce()
                        stdout, stderr = child.communicate(timeout=10)
                        if reason == "watch_timeout":
                            raise subprocess.TimeoutExpired(command, timeout, output=stdout, stderr=stderr)
                        return subprocess.CompletedProcess(command, 2, stdout, stderr)
        except BaseException:
            # Idempotent quiescence also covers cancellation and local client failures.
            try:
                quiesce()
            finally:
                if child.poll() is None:
                    child.kill()
                child.communicate()
            raise

"""Sanitized route checks shared by the recovery controller and owned client."""

from pathlib import Path as _ArchivePath
import sys as _archive_sys
_archive_sys.path.insert(0, str(next(p for p in _ArchivePath(__file__).resolve().parents if (p / "archive_gate.py").is_file())))
from archive_gate import require_enabled, path as _archive_path, setting as _archive_setting, runtime_root as _archive_root
require_enabled()

from pathlib import Path
import subprocess
import time


def failure_reason(path: Path, *, active: bool) -> str | None:
    from run_next_batch import read_events
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


def run_owned_client(command, *, container_id, timeout, diagnostics):
    """Stop only the owned operator container; let the episode driver clean up."""
    started = time.monotonic()
    with subprocess.Popen(command, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE) as child:
        reason = None
        stop_started = None
        while True:
            try:
                stdout, stderr = child.communicate(timeout=0.25)
                return subprocess.CompletedProcess(command, child.returncode if not reason else 2, stdout, stderr)
            except subprocess.TimeoutExpired:
                if reason is None:
                    reason = failure_reason(diagnostics, active=True)
                    if time.monotonic() - started >= timeout:
                        reason = "watch_timeout"
                    if reason:
                        stop_started = time.monotonic()
                        print("FAILED", "owned_operator", reason, flush=True)
                        # The driver still owns relay, broker, credentials and plant cleanup.
                        try:
                            stopped = subprocess.run(["docker", "stop", "--time", "2", container_id],
                                                     capture_output=True, text=True, timeout=10)
                            if stopped.returncode:
                                print("FAILED", "owned_operator_stop", flush=True)
                        except (OSError, subprocess.TimeoutExpired):
                            print("FAILED", "owned_operator_stop", flush=True)
                if reason and time.monotonic() - stop_started >= 15:
                    # This handle is our docker-exec client, never the episode driver.
                    child.terminate()
                    try:
                        stdout, stderr = child.communicate(timeout=5)
                    except subprocess.TimeoutExpired:
                        child.kill()
                        stdout, stderr = child.communicate()
                    return subprocess.CompletedProcess(command, 2, stdout, stderr)

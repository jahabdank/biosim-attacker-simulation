"""HTTP client for stock BioSim REST (:8009/api/simulation)."""

from __future__ import annotations

from pathlib import Path as _ArchivePath
import sys as _archive_sys
_archive_sys.path.insert(0, str(next(p for p in _ArchivePath(__file__).resolve().parents if (p / "archive_gate.py").is_file())))
from archive_gate import require_enabled, path as _archive_path, setting as _archive_setting, runtime_root as _archive_root
require_enabled()


import json
import urllib.error
import urllib.request
from typing import Any


class BioSimError(RuntimeError):
    def __init__(self, message: str, status: int | None = None, body: str = ""):
        super().__init__(message)
        self.status = status
        self.body = body


class BioSimClient:
    def __init__(self, base_url: str = _archive_setting('endpoint_001'), timeout: float = 30.0):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def _request(
        self,
        method: str,
        path: str,
        body: bytes | None = None,
        content_type: str | None = None,
        timeout: float | None = None,
    ) -> Any:
        url = f"{self.base_url}{path}"
        headers = {}
        if content_type:
            headers["Content-Type"] = content_type
        req = urllib.request.Request(url, data=body, method=method, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=timeout or self.timeout) as resp:
                raw = resp.read()
        except urllib.error.HTTPError as exc:
            err_body = exc.read().decode("utf-8", errors="replace")
            raise BioSimError(
                f"{method} {path} -> HTTP {exc.code}: {err_body[:400]}",
                status=exc.code,
                body=err_body,
            ) from exc
        except urllib.error.URLError as exc:
            raise BioSimError(f"{method} {path} failed: {exc}") from exc
        if not raw:
            return None
        return json.loads(raw.decode("utf-8"))

    def ping(self) -> dict[str, Any]:
        return self._request("GET", "/api/simulation")

    def list_simulations(self) -> list[int]:
        payload = self.ping()
        return list(payload.get("simulations", []))

    def start(self, xml_config: str) -> int:
        result = self._request(
            "POST",
            "/api/simulation/start",
            body=xml_config.encode("utf-8"),
            content_type="application/xml",
        )
        if not isinstance(result, dict) or "simId" not in result:
            raise BioSimError(f"start did not return simId: {result!r}")
        return int(result["simId"])

    def snapshot(self, sim_id: int) -> dict[str, Any]:
        return self._request("GET", f"/api/simulation/{sim_id}")

    def module(self, sim_id: int, module: str) -> dict[str, Any]:
        return self._request("GET", f"/api/simulation/{sim_id}/modules/{module}")

    def tick(self, sim_id: int) -> int:
        result = self._request("POST", f"/api/simulation/{sim_id}/tick")
        return int(result["ticks"])

    def advance_time(self, sim_id: int, n_ticks: int) -> int:
        """Advance n BioSim ticks. Plant hours = n * tickLength.

        Prefers POST /tick?n=N (in-process loop, returns ``advanced``).
        Old jars ignore the query param and tick once; we finish the rest
        one POST at a time.
        """
        if n_ticks < 1:
            raise ValueError("n_ticks must be >= 1")
        wait = max(self.timeout, 10.0 + 0.02 * n_ticks)
        result: Any = None
        try:
            result = self._request(
                "POST", f"/api/simulation/{sim_id}/tick?n={int(n_ticks)}", timeout=wait
            )
        except BioSimError:
            result = None
        if isinstance(result, dict) and int(result.get("advanced") or 0) == n_ticks:
            return int(result["ticks"])
        ticks = int(result["ticks"]) if isinstance(result, dict) and "ticks" in result else 0
        done = int(result.get("advanced") or 1) if isinstance(result, dict) else 0
        for _ in range(max(0, n_ticks - done)):
            ticks = self.tick(sim_id)
        return ticks

    def set_flow(
        self,
        sim_id: int,
        module: str,
        side: str,
        resource: str,
        desired_flow_rates: list[float],
        connections: list[str] | None = None,
    ) -> dict[str, Any]:
        if side not in {"consumers", "producers"}:
            raise ValueError("side must be 'consumers' or 'producers'")
        payload: dict[str, Any] = {"desiredFlowRates": [float(x) for x in desired_flow_rates]}
        # Only send connections when the caller named top-level modules.
        # BioSim re-resolves names via findModule; "Cabin.O2" env-stores 400.
        if connections is not None:
            payload["connections"] = connections
        return self._request(
            "POST",
            f"/api/simulation/{sim_id}/modules/{module}/{side}/{resource}",
            body=json.dumps(payload).encode("utf-8"),
            content_type="application/json",
        )

    def malfunctions(self, sim_id: int, module: str) -> list[dict[str, Any]]:
        return self._request("GET", f"/api/simulation/{sim_id}/modules/{module}/malfunctions")

    def clear_malfunction(self, sim_id: int, module: str, malfunction_id: int) -> dict[str, Any]:
        return self._request(
            "DELETE",
            f"/api/simulation/{sim_id}/modules/{module}/malfunctions/{int(malfunction_id)}",
        )

"""HTTP client for stock BioSim REST (:8009/api/simulation)."""

from __future__ import annotations

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
    def __init__(self, base_url: str = "http://127.0.0.1:8009", timeout: float = 30.0):
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
        """Advance once; an ambiguous mutation acknowledgement must never be retried."""
        if type(n_ticks) is not int or n_ticks < 1:
            raise ValueError("n_ticks must be a positive integer")
        wait = max(self.timeout, 10.0 + 0.02 * n_ticks)
        try:
            result = self._request(
                "POST", f"/api/simulation/{sim_id}/tick?n={n_ticks}", timeout=wait
            )
        except (BioSimError, OSError, ValueError) as exc:
            raise BioSimError("tick batch acknowledgement unavailable; progress is unknown") from exc
        if (not isinstance(result, dict) or type(result.get("advanced")) is not int
                or not 0 <= result["advanced"] <= n_ticks or type(result.get("ticks")) is not int
                or result["ticks"] < result["advanced"]):
            raise BioSimError("tick batch acknowledgement invalid; progress is unknown")
        if result["advanced"] < n_ticks:
            try:
                snapshot = self.snapshot(sim_id)
            except (BioSimError, OSError, ValueError) as exc:
                raise BioSimError("terminal tick snapshot unavailable; progress is unknown") from exc
            state = snapshot.get("globals") if isinstance(snapshot, dict) else None
            if (not isinstance(state, dict) or state.get("simulationEnded") is not True
                    or type(state.get("ticksGoneBy")) is not int or state["ticksGoneBy"] != result["ticks"]):
                raise BioSimError("short tick batch lacks a matching terminal snapshot; progress is unknown")
        return result["ticks"]

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

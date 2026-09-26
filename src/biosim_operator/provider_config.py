"""Explicit provider configuration; public labels are independent of transport addresses."""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import tomllib
from urllib.parse import urlsplit


def load_provider(model: str) -> dict:
    path = os.environ.get("BIOSIM_PROVIDERS", "")
    if not path:
        raise ValueError("BIOSIM_PROVIDERS must name a provider TOML file")
    data = tomllib.loads(Path(path).read_text())
    value = dict(data.get("models", {}).get(model, {}))
    if not value:
        raise ValueError("model is not configured")
    if value.get("kind") not in {"api", "subscription"}:
        raise ValueError("provider kind must be api or subscription")
    for name in ("context_window", "max_completion_tokens"):
        if name == "max_completion_tokens" and value["kind"] == "subscription":
            value.setdefault(name, None)
            continue
        if type(value.get(name)) is not int or value[name] <= 0:
            raise ValueError(f"{name} must be a positive integer")
    if not re.fullmatch(r"[A-Za-z0-9_.-]+", value.get("pacing_group", model)):
        raise ValueError("invalid pacing_group")
    value.setdefault("model", model)
    value.setdefault("label", model)
    if value["kind"] == "api":
        if value.get("api_backend") not in {"chat_completions", "responses"}:
            raise ValueError("api_backend must be chat_completions or responses")
        url = urlsplit(value.get("base_url", ""))
        if url.scheme not in {"http", "https"} or not url.hostname or url.username or url.password or url.query or url.fragment:
            raise ValueError("base_url must be an HTTP(S) URL without credentials, query or fragment")
        header = value.get("auth_header", "Authorization")
        if not re.fullmatch(r"[A-Za-z0-9-]+", header):
            raise ValueError("invalid auth_header")
        if "\n" in value.get("auth_prefix", "Bearer ") or "\r" in value.get("auth_prefix", "Bearer "):
            raise ValueError("invalid auth_prefix")
    return value


def credential(provider: dict) -> str:
    path = provider.get("credential_file", "")
    if not path:
        if provider.get("allow_unauthenticated") is True:
            return ""
        raise ValueError("credential_file is required")
    try:
        value = Path(path).expanduser().read_text().strip()
    except OSError:
        raise ValueError("credential file unavailable") from None
    if not value or "\n" in value or "\r" in value:
        raise ValueError("credential file is empty or invalid")
    return value


def model_toml(model: str, provider: dict, base_url: str) -> str:
    fields = {"model": model, "name": provider.get("label", model),
              "base_url": base_url, "api_key": "episode-local-no-secret",
              "api_backend": provider["api_backend"],
              "context_window": provider["context_window"],
              "max_completion_tokens": provider["max_completion_tokens"]}
    return "\n[model." + json.dumps(model) + "]\n" + "".join(
        key + " = " + json.dumps(value) + "\n" for key, value in fields.items())


def require_live() -> None:
    if os.environ.get("BIOSIM_ALLOW_LIVE") != "1":
        raise RuntimeError("Live inference is disabled; use the launcher with --allow-live")

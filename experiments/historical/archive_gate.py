"""Explicit gate and deployment bindings for preserved historical experiment code."""
from pathlib import Path
import os
import tomllib


def require_enabled() -> None:
    if os.environ.get("BIOSIM_ARCHIVE_ENABLE") != "1":
        raise RuntimeError("Historical code is inert; read historical/README.md before enabling it")
    filename = os.environ.get("BIOSIM_ARCHIVE_CONFIG")
    if not filename or not Path(filename).is_file():
        raise RuntimeError("BIOSIM_ARCHIVE_CONFIG must name explicit local deployment bindings")
    config = tomllib.loads(Path(filename).read_text())
    if config.get("execution", {}).get("allow_side_effects") is not True or os.environ.get("BIOSIM_ALLOW_LIVE") != "1":
        raise RuntimeError("Archived execution requires explicit side-effect and live-inference authorization")


def setting(name: str) -> str:
    require_enabled()
    config = tomllib.loads(Path(os.environ["BIOSIM_ARCHIVE_CONFIG"]).read_text())
    value = config.get("settings", {}).get(name)
    if not isinstance(value, str) or not value:
        raise RuntimeError(f"Archived deployment binding is required: {name}")
    return value


def path(name: str) -> Path:
    return Path(setting(name)).expanduser().resolve()


def runtime_root() -> Path:
    return Path(__file__).resolve().parent / "runtime"


def port(name: str) -> int:
    value = setting(name)
    if not value.isascii() or not value.isdecimal() or not 1 <= int(value) <= 65535:
        raise RuntimeError(f"Archived gateway port must be decimal and in range: {name}")
    return int(value)


def credential(name: str) -> str:
    try:
        value = path(name).read_text(encoding="utf-8").strip()
    except (OSError, UnicodeError):
        raise RuntimeError("Archived credential file unavailable") from None
    if not value or "\r" in value or "\n" in value:
        raise RuntimeError("Archived credential file must contain one nonempty value")
    return value

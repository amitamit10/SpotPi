"""Profile file operations."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from .config import ConfigError, dumps_toml, load_config, save_config, validate_config

PROFILE_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")


def profile_dir(config: dict[str, Any]) -> Path:
    return Path(config["profiles"]["directory"])


def safe_profile_name(name: str) -> str:
    cleaned = name.strip()
    if cleaned.endswith(".toml"):
        cleaned = cleaned[:-5]
    if not PROFILE_NAME_RE.match(cleaned):
        raise ConfigError("Profile name must use letters, numbers, dot, dash, or underscore")
    return cleaned


def profile_path(config: dict[str, Any], name: str) -> Path:
    return profile_dir(config) / f"{safe_profile_name(name)}.toml"


def list_profiles(config: dict[str, Any]) -> list[dict[str, Any]]:
    directory = profile_dir(config)
    if not directory.exists():
        return []
    profiles = []
    for item in sorted(directory.glob("*.toml")):
        profiles.append({"name": item.stem, "path": str(item), "size": item.stat().st_size})
    return profiles


def save_profile(config: dict[str, Any], name: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    directory = profile_dir(config)
    directory.mkdir(parents=True, exist_ok=True)
    data = validate_config(payload or config)
    path = profile_path(config, name)
    path.write_text(dumps_toml(data), encoding="utf-8")
    return {"name": path.stem, "path": str(path)}


def load_profile(config: dict[str, Any], name: str) -> dict[str, Any]:
    loaded = load_config(profile_path(config, name))
    return save_config(loaded)


def delete_profile(config: dict[str, Any], name: str) -> dict[str, Any]:
    path = profile_path(config, name)
    if path.exists():
        path.unlink()
    return {"name": path.stem, "deleted": True}

"""TOML configuration loading, validation, and saving."""

from __future__ import annotations

import copy
import os
import re
import shutil
import tempfile
try:
    import tomllib
except ImportError:
    import tomli as tomllib

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .defaults import CONFIG_SCHEMA, DEFAULT_CONFIG, SECTION_LABELS, SECTION_ORDER

CONFIG_PATH_ENV = "PCS_CONFIG"
DEFAULT_CONFIG_PATH = "/etc/spotpi/config.toml"


class ConfigError(ValueError):
    """Raised when a configuration value is invalid."""


BACKUP_RE = re.compile(r"^config-\d{8}T\d{6}(?:\d{6})?Z\.toml$")


def default_config_path() -> Path:
    return Path(os.environ.get(CONFIG_PATH_ENV, DEFAULT_CONFIG_PATH))


def schema_payload() -> dict[str, Any]:
    return {
        "sections": [{"key": key, "label": SECTION_LABELS[key]} for key in SECTION_ORDER],
        "fields": CONFIG_SCHEMA,
    }


def deep_copy_defaults() -> dict[str, Any]:
    return copy.deepcopy(DEFAULT_CONFIG)


def deep_merge(base: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
    result = copy.deepcopy(base)
    for key, value in patch.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def load_config(path: Path | None = None) -> dict[str, Any]:
    config_path = path or default_config_path()
    if not config_path.exists():
        return validate_config(deep_copy_defaults())
    with config_path.open("rb") as handle:
        loaded = tomllib.load(handle)
    return validate_config(deep_merge(deep_copy_defaults(), loaded))


def save_config(config: dict[str, Any], path: Path | None = None) -> dict[str, Any]:
    config_path = path or default_config_path()
    validated = validate_config(config)
    config_path.parent.mkdir(parents=True, exist_ok=True)
    maybe_backup_current_config(config_path, validated)
    encoded = dumps_toml(validated)
    with tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        dir=str(config_path.parent),
        delete=False,
    ) as handle:
        handle.write(encoded)
        temp_name = handle.name
    os.replace(temp_name, config_path)
    return validated


def update_config(patch: dict[str, Any], path: Path | None = None) -> dict[str, Any]:
    current = load_config(path)
    return save_config(deep_merge(current, patch), path)


def validate_config(config: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(config, dict):
        raise ConfigError("Configuration must be an object")

    validated: dict[str, Any] = {}
    for section in SECTION_ORDER:
        source_section = config.get(section, {})
        if not isinstance(source_section, dict):
            raise ConfigError(f"Section '{section}' must be an object")

        validated[section] = {}
        known_keys = {field["key"] for field in CONFIG_SCHEMA[section]}
        unknown = sorted(set(source_section) - known_keys)
        if unknown:
            raise ConfigError(f"Unknown setting in '{section}': {', '.join(unknown)}")

        for field in CONFIG_SCHEMA[section]:
            key = field["key"]
            default_value = DEFAULT_CONFIG[section][key]
            value = source_section.get(key, default_value)
            validated[section][key] = validate_value(section, field, value)
    return validated


def maybe_backup_current_config(config_path: Path, config: dict[str, Any]) -> None:
    backup = config.get("backup", {})
    if not backup.get("enabled") or not config_path.exists():
        return
    try:
        backup_dir = Path(str(backup["directory"]))
        backup_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        backup_path = backup_dir / f"config-{timestamp}.toml"
        shutil.copy2(config_path, backup_path)
        prune_backups(backup_dir, int(backup["keep_last"]))
    except OSError:
        # A failed backup should not leave the device unconfigurable.
        return


def prune_backups(directory: Path, keep_last: int) -> None:
    backups = sorted(list_backups_in_dir(directory), key=lambda item: item["name"], reverse=True)
    for item in backups[keep_last:]:
        try:
            Path(item["path"]).unlink()
        except OSError:
            continue


def list_backups(config: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    loaded = config or load_config()
    return list_backups_in_dir(Path(str(loaded["backup"]["directory"])))


def list_backups_in_dir(directory: Path) -> list[dict[str, Any]]:
    if not directory.exists():
        return []
    backups: list[dict[str, Any]] = []
    for item in sorted(directory.glob("config-*.toml"), reverse=True):
        if not BACKUP_RE.match(item.name):
            continue
        stat = item.stat()
        backups.append(
            {
                "name": item.name,
                "path": str(item),
                "size": stat.st_size,
                "modified": datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(),
            }
        )
    return backups


def restore_backup(name: str, config: dict[str, Any] | None = None, path: Path | None = None) -> dict[str, Any]:
    if not BACKUP_RE.match(name):
        raise ConfigError("Invalid backup name")
    loaded = config or load_config(path)
    source = Path(str(loaded["backup"]["directory"])) / name
    if not source.exists():
        raise ConfigError("Backup not found")
    with source.open("rb") as handle:
        backup_config = tomllib.load(handle)
    return save_config(validate_config(deep_merge(deep_copy_defaults(), backup_config)), path)


def validate_value(section: str, field: dict[str, Any], value: Any) -> Any:
    key = field["key"]
    field_type = field["type"]
    label = f"{section}.{key}"

    if field_type in {"string", "secret"}:
        if value is None:
            value = ""
        if not isinstance(value, str):
            raise ConfigError(f"{label} must be a string")
        if field.get("required") and value.strip() == "":
            raise ConfigError(f"{label} is required")
        return value.strip() if field.get("trim", True) else value

    if field_type == "boolean":
        if not isinstance(value, bool):
            raise ConfigError(f"{label} must be true or false")
        return value

    if field_type == "integer":
        if isinstance(value, bool) or not isinstance(value, int):
            raise ConfigError(f"{label} must be an integer")
        return validate_range(label, value, field)

    if field_type == "float":
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ConfigError(f"{label} must be a number")
        return float(validate_range(label, float(value), field))

    if field_type == "enum":
        choices = field["choices"]
        if value not in choices:
            rendered = ", ".join(str(choice) for choice in choices)
            raise ConfigError(f"{label} must be one of: {rendered}")
        return value

    if field_type == "string_list":
        if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
            raise ConfigError(f"{label} must be a list of strings")
        return [item.strip() for item in value if item.strip()]

    raise ConfigError(f"Unsupported field type for {label}: {field_type}")


def validate_range(label: str, value: int | float, field: dict[str, Any]) -> int | float:
    minimum = field.get("min")
    maximum = field.get("max")
    if minimum is not None and value < minimum:
        raise ConfigError(f"{label} must be at least {minimum}")
    if maximum is not None and value > maximum:
        raise ConfigError(f"{label} must be at most {maximum}")
    return value


def dumps_toml(config: dict[str, Any]) -> str:
    lines: list[str] = [
        "# SpotPi configuration",
        "# Managed by the web UI. Edit carefully if changing by hand.",
        "",
    ]
    for section in SECTION_ORDER:
        lines.append(f"[{section}]")
        for field in CONFIG_SCHEMA[section]:
            key = field["key"]
            lines.append(f"{key} = {format_toml_value(config[section][key])}")
        lines.append("")
    return "\n".join(lines)


def format_toml_value(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return repr(value)
    if isinstance(value, str):
        return quote_toml_string(value)
    if isinstance(value, list):
        return "[" + ", ".join(quote_toml_string(str(item)) for item in value) + "]"
    raise ConfigError(f"Cannot serialize value of type {type(value).__name__}")


def quote_toml_string(value: str) -> str:
    escaped = (
        value.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\b", "\\b")
        .replace("\t", "\\t")
        .replace("\n", "\\n")
        .replace("\f", "\\f")
        .replace("\r", "\\r")
    )
    return f'"{escaped}"'

"""Health checks and diagnostics for the Pi runtime."""

from __future__ import annotations

import os
import platform
import shutil
import socket
from pathlib import Path
from typing import Any

from .config import default_config_path
from .librespot import audio_device_available, build_librespot_args, redacted_args
from .system import list_audio_devices, run_command, service_status


def system_summary(config: dict[str, Any]) -> dict[str, Any]:
    return {
        "hostname": socket.gethostname(),
        "ip_addresses": ip_addresses(),
        "platform": platform.platform(),
        "machine": platform.machine(),
        "python": platform.python_version(),
        "uptime": read_first_line("/proc/uptime"),
        "cpu_temperature_c": cpu_temperature(),
        "memory": memory_info(),
        "disk": disk_info([
            "/",
            str(default_config_path().parent),
            config["quality"]["cache_path"],
        ]),
    }


def doctor(config: dict[str, Any]) -> dict[str, Any]:
    checks = [
        check_file_exists("Configuration file", default_config_path(), required=False),
        check_directory("Configuration directory", default_config_path().parent, writable=True),
        check_directory("Profile directory", Path(config["profiles"]["directory"]), writable=True),
        check_directory("Backup directory", Path(config["backup"]["directory"]), writable=True),
        check_directory("Audio cache", Path(config["quality"]["cache_path"]), writable=True),
        check_directory("System cache", Path(config["quality"]["system_cache_path"]), writable=True),
        check_binary("librespot", config["service"]["librespot_path"]),
        check_binary("aplay", "aplay"),
        check_binary("speaker-test", "speaker-test", required=config["diagnostics"]["test_sound_command"] == "speaker-test"),
        check_binary("systemctl", "systemctl"),
        check_binary("journalctl", "journalctl"),
        check_binary("avahi-daemon", "avahi-daemon", required=False),
        check_service(config, "Spotify engine", config["service"]["spotify_service_name"]),
        check_service(config, "Web UI", config["service"]["web_service_name"]),
        check_audio(config),
        check_connectivity(config),
        check_librespot_command(config),
    ]
    summary = {
        "ok": sum(1 for check in checks if check["status"] == "ok"),
        "warning": sum(1 for check in checks if check["status"] == "warning"),
        "error": sum(1 for check in checks if check["status"] == "error"),
    }
    return {"summary": summary, "checks": checks, "system": system_summary(config)}


def ip_addresses() -> list[str]:
    result = run_command(["hostname", "-I"], timeout=3)
    if result.ok and result.stdout:
        return [item for item in result.stdout.split() if item]
    return []


def read_first_line(path: str) -> str:
    try:
        return Path(path).read_text(encoding="utf-8").splitlines()[0]
    except (OSError, IndexError):
        return ""


def cpu_temperature() -> float | None:
    raw = read_first_line("/sys/class/thermal/thermal_zone0/temp")
    try:
        return round(int(raw) / 1000, 1)
    except ValueError:
        return None


def memory_info() -> dict[str, int]:
    values: dict[str, int] = {}
    try:
        for line in Path("/proc/meminfo").read_text(encoding="utf-8").splitlines():
            key, raw = line.split(":", 1)
            if key in {"MemTotal", "MemAvailable"}:
                values[key] = int(raw.strip().split()[0])
    except (OSError, ValueError):
        return {}
    return values


def disk_info(paths: list[str]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    disks: list[dict[str, Any]] = []
    for raw_path in paths:
        path = existing_parent(Path(raw_path))
        if str(path) in seen:
            continue
        seen.add(str(path))
        try:
            usage = shutil.disk_usage(path)
        except OSError:
            continue
        disks.append(
            {
                "path": str(path),
                "total": usage.total,
                "used": usage.used,
                "free": usage.free,
                "free_percent": round((usage.free / usage.total) * 100, 1) if usage.total else 0,
            }
        )
    return disks


def existing_parent(path: Path) -> Path:
    current = path
    while not current.exists() and current != current.parent:
        current = current.parent
    return current


def check(name: str, status: str, detail: str, fix: str = "") -> dict[str, str]:
    return {"name": name, "status": status, "detail": detail, "fix": fix}


def check_binary(name: str, binary: str, required: bool = True) -> dict[str, str]:
    path = binary if "/" in binary else shutil.which(binary)
    if path and Path(path).exists():
        return check(name, "ok", str(path))
    status = "error" if required else "warning"
    return check(name, status, f"{binary} was not found", f"Install {name} or update the configured path")


def check_file_exists(name: str, path: Path, required: bool = True) -> dict[str, str]:
    if path.exists():
        return check(name, "ok", str(path))
    return check(name, "error" if required else "warning", f"{path} does not exist", "Run the installer or save settings once")


def check_directory(name: str, path: Path, writable: bool = False) -> dict[str, str]:
    if not path.exists():
        parent = existing_parent(path)
        if writable and os.access(parent, os.W_OK):
            return check(name, "warning", f"{path} does not exist yet", "It will be created on first save or install")
        return check(name, "warning", f"{path} does not exist", "Run the installer")
    if not path.is_dir():
        return check(name, "error", f"{path} is not a directory", "Fix the path in settings")
    if writable and not os.access(path, os.W_OK):
        return check(name, "warning", f"{path} is not writable by this process", "Check ownership and permissions")
    return check(name, "ok", str(path))


def check_service(config: dict[str, Any], name: str, service_name: str) -> dict[str, str]:
    status = service_status(config, service_name)
    if status["active"] == "active":
        return check(name, "ok", f"{service_name} is active")
    if status["active"] in {"inactive", "unknown"}:
        return check(name, "warning", f"{service_name} is {status['active']}", f"Start {service_name}")
    return check(name, "error", f"{service_name} is {status['active']}", f"Check journalctl -u {service_name}")


def check_audio(config: dict[str, Any]) -> dict[str, str]:
    devices = list_audio_devices(config)
    if config["audio"]["device_selection"] == "manual":
        device = config["audio"]["device"]
        if audio_device_available(device):
            return check("Audio device", "ok", f"{device} is available")
        return check("Audio device", "error", f"{device} is not available", "Pick a detected USB DAC in Audio Devices")
    if devices["hardware"] or devices["logical"]:
        return check("Audio device", "ok", "ALSA returned audio devices")
    return check("Audio device", "warning", "No ALSA devices were returned", "Connect the USB DAC and refresh")


def check_connectivity(config: dict[str, Any]) -> dict[str, str]:
    host = config["network"]["connectivity_host"]
    try:
        with socket.create_connection((host, 53), timeout=2):
            return check("Network connectivity", "ok", f"Connected to {host}:53")
    except OSError as exc:
        return check("Network connectivity", "warning", f"{host}:53 is not reachable: {exc}", "Check Wi-Fi or change connectivity host")


def check_librespot_command(config: dict[str, Any]) -> dict[str, str]:
    args = redacted_args(build_librespot_args(config, include_executable=True))
    if args:
        return check("Librespot command", "ok", " ".join(args))
    return check("Librespot command", "error", "No command generated", "Check service settings")

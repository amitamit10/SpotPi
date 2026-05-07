"""System command wrappers used by the web API."""

from __future__ import annotations

import os
import re
import shlex
import shutil
import subprocess
import time
from dataclasses import dataclass
from typing import Any

from .librespot import build_librespot_args, redacted_args

SERVICE_RE = re.compile(r"^[A-Za-z0-9_.@-]+\.service$")
ALLOWED_ACTIONS = {"start", "stop", "restart", "enable", "disable", "enable-now", "disable-now"}


@dataclass
class CommandResult:
    ok: bool
    returncode: int | None
    stdout: str
    stderr: str
    command: list[str]

    def as_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "returncode": self.returncode,
            "stdout": self.stdout,
            "stderr": self.stderr,
            "command": self.command,
        }


def run_command(args: list[str], timeout: int = 10) -> CommandResult:
    started = time.monotonic()
    try:
        completed = subprocess.run(
            args,
            text=True,
            capture_output=True,
            timeout=timeout,
            check=False,
        )
        return CommandResult(
            ok=completed.returncode == 0,
            returncode=completed.returncode,
            stdout=completed.stdout.strip(),
            stderr=completed.stderr.strip(),
            command=args,
        )
    except FileNotFoundError as exc:
        return CommandResult(False, None, "", str(exc), args)
    except subprocess.TimeoutExpired as exc:
        elapsed = round(time.monotonic() - started, 2)
        return CommandResult(
            False,
            None,
            exc.stdout.strip() if isinstance(exc.stdout, str) else "",
            f"Command timed out after {elapsed}s",
            args,
        )


def command_timeout(config: dict[str, Any]) -> int:
    return int(config["stability"]["command_timeout_seconds"])


def system_prefix() -> list[str]:
    if hasattr(os, "geteuid") and os.geteuid() == 0:
        return []
    sudo = shutil.which("sudo")
    return [sudo, "-n"] if sudo else []


def validate_service_name(name: str) -> str:
    if not SERVICE_RE.match(name):
        raise ValueError(f"Invalid service name: {name}")
    return name


def systemctl(config: dict[str, Any], action: str, service_name: str) -> CommandResult:
    if action not in ALLOWED_ACTIONS:
        raise ValueError(f"Unsupported service action: {action}")
    service = validate_service_name(service_name)
    systemd_action = action.replace("-now", "")
    args = [*system_prefix(), "systemctl", systemd_action]
    if action.endswith("-now"):
        args.append("--now")
    args.append(service)
    return run_command(args, timeout=command_timeout(config))


def service_name_for_target(config: dict[str, Any], target: str) -> str:
    if target == "spotify":
        return config["service"]["spotify_service_name"]
    if target == "web":
        return config["service"]["web_service_name"]
    raise ValueError(f"Unsupported service target: {target}")


def systemctl_target(config: dict[str, Any], action: str, target: str) -> CommandResult:
    return systemctl(config, action, service_name_for_target(config, target))


def service_status(config: dict[str, Any], service_name: str) -> dict[str, Any]:
    service = validate_service_name(service_name)
    timeout = command_timeout(config)
    active = run_command(["systemctl", "is-active", service], timeout=timeout)
    enabled = run_command(["systemctl", "is-enabled", service], timeout=timeout)
    return {
        "service": service,
        "active": active.stdout if active.stdout else "unknown",
        "enabled": enabled.stdout if enabled.stdout else "unknown",
        "active_ok": active.ok,
        "enabled_ok": enabled.ok,
        "errors": [err for err in [active.stderr, enabled.stderr] if err],
    }


def journal_logs(config: dict[str, Any], service_name: str, lines: int | None = None) -> CommandResult:
    service = validate_service_name(service_name)
    line_count = lines or int(config["diagnostics"]["log_lines"])
    line_count = max(20, min(line_count, 2000))
    args = [
        *system_prefix(),
        "journalctl",
        "-u",
        service,
        "-n",
        str(line_count),
        "--no-pager",
        "--output=short-iso",
    ]
    return run_command(args, timeout=command_timeout(config))


def journal_logs_for_target(config: dict[str, Any], target: str, lines: int | None = None) -> CommandResult:
    return journal_logs(config, service_name_for_target(config, target), lines)


def list_audio_devices(config: dict[str, Any]) -> dict[str, Any]:
    timeout = command_timeout(config)
    hardware = run_command(["aplay", "-l"], timeout=timeout)
    logical = run_command(["aplay", "-L"], timeout=timeout)
    return {
        "hardware": parse_aplay_hardware(hardware.stdout),
        "logical": parse_aplay_logical(logical.stdout),
        "raw": {
            "hardware": hardware.as_dict(),
            "logical": logical.as_dict(),
        },
        "mixer": mixer_controls(config),
    }


def parse_aplay_hardware(output: str) -> list[dict[str, Any]]:
    devices: list[dict[str, Any]] = []
    pattern = re.compile(r"^card\s+(\d+):\s+([^\[]+)\[([^\]]+)\],\s+device\s+(\d+):\s+([^\[]+)\[([^\]]+)\]")
    for line in output.splitlines():
        match = pattern.match(line.strip())
        if not match:
            continue
        card, card_id, card_name, device, device_id, device_name = match.groups()
        devices.append(
            {
                "id": f"hw:{card},{device}",
                "card": int(card),
                "card_id": card_id.strip(),
                "card_name": card_name.strip(),
                "device": int(device),
                "device_id": device_id.strip(),
                "device_name": device_name.strip(),
            }
        )
    return devices


def parse_aplay_logical(output: str) -> list[str]:
    names: list[str] = []
    for line in output.splitlines():
        if not line or line.startswith(" "):
            continue
        if line.startswith(("null", "default", "sysdefault", "front", "surround", "iec958", "hw:", "plughw:")):
            names.append(line.strip())
    return names


def mixer_device(config: dict[str, Any]) -> str:
    audio = config["audio"]
    if audio["alsa_mixer_device"]:
        return audio["alsa_mixer_device"]
    if audio["device_selection"] == "manual":
        return audio["device"]
    return "default"


def mixer_controls(config: dict[str, Any]) -> dict[str, Any]:
    device = mixer_device(config)
    result = run_command(["amixer", "-D", device, "scontrols"], timeout=command_timeout(config))
    return {
        "device": device,
        "controls": parse_amixer_controls(result.stdout),
        "raw": result.as_dict(),
    }


def parse_amixer_controls(output: str) -> list[str]:
    controls: list[str] = []
    pattern = re.compile(r"^Simple mixer control '(.+)'")
    for line in output.splitlines():
        match = pattern.match(line.strip())
        if match:
            controls.append(match.group(1))
    return controls


def mixer_state(config: dict[str, Any]) -> dict[str, Any]:
    device = mixer_device(config)
    control = config["audio"]["alsa_mixer_control"]
    result = run_command(["amixer", "-D", device, "sget", control], timeout=command_timeout(config))
    return {
        "device": device,
        "control": control,
        "volume_percent": parse_amixer_volume(result.stdout),
        "raw": result.as_dict(),
    }


def parse_amixer_volume(output: str) -> int | None:
    matches = re.findall(r"\[(\d{1,3})%\]", output)
    if not matches:
        return None
    values = [max(0, min(int(match), 100)) for match in matches]
    return round(sum(values) / len(values))


def set_mixer_volume(config: dict[str, Any], percent: int) -> CommandResult:
    bounded = max(0, min(int(percent), 100))
    device = mixer_device(config)
    control = config["audio"]["alsa_mixer_control"]
    return run_command(
        ["amixer", "-D", device, "sset", control, f"{bounded}%"],
        timeout=command_timeout(config),
    )


def test_sound(config: dict[str, Any]) -> CommandResult:
    diagnostics = config["diagnostics"]
    command = diagnostics["test_sound_command"]
    if command == "disabled":
        return CommandResult(False, None, "", "Test sound is disabled", [])

    audio = config["audio"]
    device = audio["device"] if audio["device_selection"] == "manual" else "default"
    timeout = int(diagnostics["test_sound_duration_seconds"]) + command_timeout(config)

    if command == "speaker-test":
        args = [
            "speaker-test",
            "-D",
            device,
            "-t",
            "sine",
            "-f",
            str(diagnostics["test_sound_frequency_hz"]),
            "-l",
            "1",
        ]
    else:
        args = ["aplay", "-D", device, "/usr/share/sounds/alsa/Front_Center.wav"]
    return run_command(args, timeout=timeout)


def status_payload(config: dict[str, Any]) -> dict[str, Any]:
    spotify_service = config["service"]["spotify_service_name"]
    web_service = config["service"]["web_service_name"]
    librespot_args = redacted_args(build_librespot_args(config, include_executable=True))
    return {
        "spotify": service_status(config, spotify_service),
        "web": service_status(config, web_service),
        "device_name": config["device"]["name"],
        "librespot_args": librespot_args,
        "paths": {
            "librespot": config["service"]["librespot_path"],
            "cache": config["quality"]["cache_path"],
            "system_cache": config["quality"]["system_cache_path"],
        },
        "command": shlex.join(librespot_args),
    }

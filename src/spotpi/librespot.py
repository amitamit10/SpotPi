"""Build and execute the configured librespot command."""

from __future__ import annotations

import os
import re
import socket
import subprocess
import sys
import time
from typing import Any

from .config import load_config


SECRET_KEYS = {"access_token"}


def resolved_device_name(config: dict[str, Any]) -> str:
    name = config["device"]["name"]
    if config["device"]["append_hostname"]:
        name = f"{name} ({socket.gethostname()})"
    return name


def build_librespot_args(config: dict[str, Any], include_executable: bool = True) -> list[str]:
    args: list[str] = []
    if include_executable:
        args.append(config["service"]["librespot_path"])

    args.extend(["--name", resolved_device_name(config)])
    args.extend(["--device-type", config["device"]["type"]])

    service = config["service"]
    if service["log_level"] == "quiet":
        args.append("--quiet")
    elif service["log_level"] == "verbose":
        args.append("--verbose")

    audio = config["audio"]
    args.extend(["--backend", audio["backend"]])
    if audio["device_selection"] == "manual" or audio["device"] != "default":
        args.extend(["--device", audio["device"]])
    args.extend(["--format", audio["format"]])
    args.extend(["--dither", audio["dither"]])
    args.extend(["--mixer", audio["mixer"]])
    if audio["mixer"] == "alsa":
        args.extend(["--alsa-mixer-control", audio["alsa_mixer_control"]])
        args.extend(["--alsa-mixer-device", audio["alsa_mixer_device"]])
        args.extend(["--alsa-mixer-index", str(audio["alsa_mixer_index"])])

    volume = config["volume"]
    args.extend(["--initial-volume", str(volume["startup_volume_percent"])])
    args.extend(["--volume-ctrl", volume["volume_control"]])
    args.extend(["--volume-range", str(volume["volume_range_db"])])
    if volume["normalisation_enabled"]:
        args.append("--enable-volume-normalisation")
        args.extend(["--normalisation-method", volume["normalisation_method"]])
        args.extend(["--normalisation-gain-type", volume["normalisation_gain_type"]])
        args.extend(["--normalisation-pregain", str(volume["normalisation_pregain_db"])])
        args.extend(["--normalisation-threshold", str(volume["normalisation_threshold_dbfs"])])

    quality = config["quality"]
    args.extend(["--bitrate", str(quality["bitrate_kbps"])])
    if quality["cache_enabled"]:
        args.extend(["--cache", quality["cache_path"]])
        args.extend(["--system-cache", quality["system_cache_path"]])
        args.extend(["--cache-size-limit", quality["cache_size_limit"]])
    else:
        args.append("--disable-audio-cache")
    if quality["autoplay_enabled"]:
        args.extend(["--autoplay", "on"])
    if not quality["gapless_enabled"]:
        args.append("--disable-gapless")

    if service["zeroconf_backend"] != "auto":
        args.extend(["--zeroconf-backend", service["zeroconf_backend"]])
    if service["zeroconf_port"] > 0:
        args.extend(["--zeroconf-port", str(service["zeroconf_port"])])
    if service["zeroconf_interface"]:
        args.extend(["--zeroconf-interface", service["zeroconf_interface"]])

    librespot = config["librespot"]
    if librespot["enable_oauth"]:
        args.append("--enable-oauth")
        args.extend(["--oauth-port", str(librespot["oauth_port"])])
    if librespot["access_token"]:
        args.extend(["--access-token", librespot["access_token"]])
    if librespot["username"]:
        args.extend(["--username", librespot["username"]])
    args.extend(librespot["extra_args"])
    return args


def prepare_runtime(config: dict[str, Any]) -> dict[str, Any]:
    wait_for_network(config)
    return prepare_audio_device(config)


def wait_for_network(config: dict[str, Any]) -> None:
    network = config["network"]
    if not network["wait_for_network"]:
        return
    host = network["connectivity_host"]
    deadline = time.monotonic() + int(network["restart_after_offline_seconds"])
    interval = int(network["retry_interval_seconds"])
    while True:
        try:
            with socket.create_connection((host, 53), timeout=2):
                return
        except OSError:
            if time.monotonic() >= deadline:
                print(f"Network connectivity check failed for {host}", file=sys.stderr)
                raise SystemExit(75)
            time.sleep(interval)


def prepare_audio_device(config: dict[str, Any]) -> dict[str, Any]:
    audio = config["audio"]
    require_device = bool(config["stability"]["require_audio_device_before_start"])
    if audio["device_selection"] != "manual":
        return config
    if audio["fallback"] == "disabled":
        if require_device and not audio_device_available(audio["device"]):
            print(f"Required audio device not available: {audio['device']}", file=sys.stderr)
            raise SystemExit(75)
        return config
    if audio_device_available(audio["device"]):
        return config
    if audio["fallback"] == "default":
        adjusted = {section: values.copy() for section, values in config.items()}
        adjusted["audio"] = config["audio"].copy()
        adjusted["audio"]["device_selection"] = "auto"
        adjusted["audio"]["device"] = "default"
        return adjusted

    network = config["network"]
    deadline = time.monotonic() + int(network["restart_after_offline_seconds"])
    interval = int(network["retry_interval_seconds"])
    while True:
        if audio_device_available(audio["device"]):
            return config
        if time.monotonic() >= deadline:
            print(f"Audio device not available: {audio['device']}", file=sys.stderr)
            raise SystemExit(75)
        time.sleep(interval)


def audio_device_available(device: str) -> bool:
    if device in {"", "default"}:
        return True
    logical = run_probe(["aplay", "-L"])
    if any(line.strip() == device for line in logical.splitlines()):
        return True
    hardware = run_probe(["aplay", "-l"])
    match = re.match(r"^hw:(\d+),(\d+)$", device)
    if not match:
        return device in hardware
    card, dev = match.groups()
    return re.search(rf"card\s+{card}:.*device\s+{dev}:", hardware) is not None


def run_probe(args: list[str]) -> str:
    try:
        return subprocess.run(args, text=True, capture_output=True, timeout=5, check=False).stdout
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return ""


def redacted_args(args: list[str]) -> list[str]:
    redacted: list[str] = []
    redact_next = False
    for arg in args:
        if redact_next:
            redacted.append("REDACTED")
            redact_next = False
            continue
        redacted.append(arg)
        if arg in {"--access-token"}:
            redact_next = True
    return redacted


def main() -> None:
    config = prepare_runtime(load_config())
    args = build_librespot_args(config, include_executable=True)
    os.execvp(args[0], args)


def preview() -> int:
    config = load_config()
    for arg in redacted_args(build_librespot_args(config, include_executable=True)):
        print(arg)
    return 0


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "preview":
        raise SystemExit(preview())
    main()

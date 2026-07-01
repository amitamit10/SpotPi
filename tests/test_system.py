from __future__ import annotations

import unittest
from unittest.mock import patch

from spotpi.system import (
    CommandResult,
    mixer_device,
    parse_amixer_controls,
    parse_amixer_volume,
    parse_aplay_hardware,
)


class SystemParsingTests(unittest.TestCase):
    def test_parse_aplay_hardware(self) -> None:
        output = "card 1: DAC [USB Audio DAC], device 0: USB Audio [USB Audio]\n"
        devices = parse_aplay_hardware(output)
        self.assertEqual(devices[0]["id"], "hw:1,0")
        self.assertEqual(devices[0]["card_name"], "USB Audio DAC")

    def test_parse_amixer_controls(self) -> None:
        output = "Simple mixer control 'PCM',0\nSimple mixer control 'Master',0\n"
        self.assertEqual(parse_amixer_controls(output), ["PCM", "Master"])

    def test_parse_amixer_volume(self) -> None:
        output = "Front Left: Playback 32768 [50%] [on]\nFront Right: Playback 32768 [52%] [on]\n"
        self.assertEqual(parse_amixer_volume(output), 51)


def _config(alsa_mixer_device: str, alsa_mixer_control: str = "PCM", timeout: int = 10) -> dict:
    return {
        "audio": {
            "alsa_mixer_device": alsa_mixer_device,
            "alsa_mixer_control": alsa_mixer_control,
            "device_selection": "manual",
            "device": alsa_mixer_device,
        },
        "stability": {"command_timeout_seconds": timeout},
    }


class MixerDeviceFallbackTests(unittest.TestCase):
    def test_falls_back_when_configured_device_has_no_ctl(self) -> None:
        """A PCM-only alias (like a softvol device with no matching control)
        should fall back to a real hardware card instead of failing outright."""
        aplay_output = "card 1: DAC [USB Audio DAC], device 0: USB Audio [USB Audio]\n"

        def fake_run_command(args: list[str], timeout: int = 10) -> CommandResult:
            if args[:2] == ["aplay", "-l"]:
                return CommandResult(True, 0, aplay_output, "", args)
            if args[:3] == ["amixer", "-D", "spotpi_vol"]:
                return CommandResult(False, 1, "", "Invalid CTL spotpi_vol", args)
            if args[:3] == ["amixer", "-D", "hw:1"]:
                return CommandResult(True, 0, "Simple mixer control 'PCM',0\n", "", args)
            raise AssertionError(f"unexpected command: {args}")

        with patch("spotpi.system.run_command", side_effect=fake_run_command):
            self.assertEqual(mixer_device(_config("spotpi_vol")), "hw:1")

    def test_keeps_configured_device_when_it_works(self) -> None:
        def fake_run_command(args: list[str], timeout: int = 10) -> CommandResult:
            return CommandResult(True, 0, "Simple mixer control 'PCM',0\n", "", args)

        with patch("spotpi.system.run_command", side_effect=fake_run_command):
            self.assertEqual(mixer_device(_config("hw:1")), "hw:1")

    def test_fallback_prefers_card_with_matching_control_name(self) -> None:
        """Even if an earlier card responds, prefer the card that actually
        exposes the configured control (e.g. a softvol control living on the
        real DAC's CTL) over the first card that merely answers scontrols —
        picking the wrong card would silently control the wrong output."""
        aplay_output = (
            "card 0: Headphones [bcm2835 Headphones], device 0: bcm2835 Headphones [bcm2835 Headphones]\n"
            "card 1: ICUSBAUDIO7D [ICUSBAUDIO7D], device 0: USB Audio [USB Audio]\n"
        )

        def fake_run_command(args: list[str], timeout: int = 10) -> CommandResult:
            if args[:2] == ["aplay", "-l"]:
                return CommandResult(True, 0, aplay_output, "", args)
            if args[:3] == ["amixer", "-D", "spotpi_vol"]:
                return CommandResult(False, 1, "", "Invalid CTL spotpi_vol", args)
            if args[:3] == ["amixer", "-D", "hw:0"]:
                return CommandResult(True, 0, "Simple mixer control 'PCM',0\n", "", args)
            if args[:3] == ["amixer", "-D", "hw:1"]:
                return CommandResult(True, 0, "Simple mixer control 'Speaker',0\nSimple mixer control 'SpotPi',0\n", "", args)
            raise AssertionError(f"unexpected command: {args}")

        with patch("spotpi.system.run_command", side_effect=fake_run_command):
            self.assertEqual(mixer_device(_config("spotpi_vol", "SpotPi")), "hw:1")


if __name__ == "__main__":
    unittest.main()

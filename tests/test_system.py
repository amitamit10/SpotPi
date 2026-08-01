from __future__ import annotations

import unittest
from unittest.mock import patch

from spotpi.config import deep_copy_defaults
from spotpi.system import (
    CommandResult,
    _db_to_alsa_percent,
    _parse_amixer_eq_bands,
    apply_eq_from_config,
    eq_available,
    eq_state,
    mixer_device,
    parse_amixer_controls,
    parse_amixer_volume,
    parse_aplay_hardware,
    reset_eq,
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


class EqualizerTests(unittest.TestCase):
    def test_db_to_alsa_percent_maps_center_to_50(self) -> None:
        self.assertEqual(_db_to_alsa_percent(0), 50)
        self.assertEqual(_db_to_alsa_percent(-12), 0)
        self.assertEqual(_db_to_alsa_percent(12), 100)
        self.assertEqual(_db_to_alsa_percent(6), 75)

    def test_db_to_alsa_percent_clamps_out_of_range(self) -> None:
        self.assertEqual(_db_to_alsa_percent(-20), 0)
        self.assertEqual(_db_to_alsa_percent(20), 100)

    def test_parse_amixer_eq_bands_extracts_first_percent(self) -> None:
        output = (
            "Simple mixer control '00. 31Hz',0\n"
            "  Capabilities: pvolume\n"
            "  Front Left: Playback 50 [50%] [on]\n"
            "  Front Right: Playback 50 [50%] [on]\n"
            "Simple mixer control '09. 16kHz',0\n"
            "  Capabilities: pvolume\n"
            "  Front Left: Playback 100 [100%] [on]\n"
        )
        self.assertEqual(_parse_amixer_eq_bands(output), {"00. 31Hz": 50, "09. 16kHz": 100})

    def test_eq_available_true_when_plugin_responds(self) -> None:
        output = "Simple mixer control '00. 31Hz',0\n  Front Left: Playback 50 [50%]\n"
        with patch("spotpi.system.run_command", return_value=CommandResult(True, 0, output, "", [])):
            self.assertTrue(eq_available())

    def test_eq_available_false_when_plugin_missing(self) -> None:
        # No amixer / no equal plugin — must degrade gracefully to False.
        with patch(
            "spotpi.system.run_command",
            return_value=CommandResult(False, None, "", "[Errno 2] No such file or directory: 'amixer'", ["amixer"]),
        ):
            self.assertFalse(eq_available())

    def test_eq_state_reports_unavailable_with_config_defaults(self) -> None:
        config = deep_copy_defaults()
        with patch("spotpi.system.run_command", return_value=CommandResult(False, 1, "", "invalid device", [])):
            state = eq_state(config)
        self.assertFalse(state["available"])
        self.assertFalse(state["enabled"])
        self.assertEqual(state["preset"], "flat")
        self.assertEqual(len(state["bands"]), 10)
        # With no hardware, each band falls back to the config value (0 dB).
        self.assertTrue(all(band["db"] == 0 for band in state["bands"]))
        self.assertTrue(all(band["hw_percent"] is None for band in state["bands"]))
        self.assertEqual(state["bands"][0]["freq"], "31Hz")
        self.assertEqual(state["bands"][-1]["freq"], "16kHz")

    def test_eq_state_reads_hw_percentages_when_available(self) -> None:
        config = deep_copy_defaults()
        config["equalizer"]["band_31hz_db"] = -6
        scontents = "Simple mixer control '00. 31Hz',0\n  Front Left: Playback 25 [25%]\n"

        def fake_run_command(args: list[str], timeout: int = 10) -> CommandResult:
            return CommandResult(True, 0, scontents, "", args)

        with patch("spotpi.system.run_command", side_effect=fake_run_command):
            state = eq_state(config)
        self.assertTrue(state["available"])
        # 25% maps to (25/100*24 - 12) = -6 dB from the live hardware state.
        self.assertEqual(state["bands"][0]["db"], -6)
        self.assertEqual(state["bands"][0]["hw_percent"], 25)

    def test_apply_eq_from_config_sets_each_band_percent(self) -> None:
        config = deep_copy_defaults()
        config["equalizer"]["band_31hz_db"] = 6
        config["equalizer"]["band_1000hz_db"] = -12

        calls: list[list[str]] = []
        def fake_run_command(args: list[str], timeout: int = 10) -> CommandResult:
            calls.append(args)
            return CommandResult(True, 0, "", "", args)

        with patch("spotpi.system.run_command", side_effect=fake_run_command):
            results = apply_eq_from_config(config)

        self.assertEqual(len(results), 10)
        self.assertTrue(all(r.ok for r in results))
        self.assertEqual(len(calls), 10)
        # +6 dB -> 75%, -12 dB -> 0%
        self.assertIn("75%", calls[0])
        self.assertIn("0%", calls[5])
        self.assertTrue(all(cmd[1:3] == ["-D", "equal"] and cmd[3] == "sset" for cmd in calls))

    def test_reset_eq_sets_all_bands_to_50_percent(self) -> None:
        config = deep_copy_defaults()

        calls: list[list[str]] = []
        def fake_run_command(args: list[str], timeout: int = 10) -> CommandResult:
            calls.append(args)
            return CommandResult(True, 0, "", "", args)

        with patch("spotpi.system.run_command", side_effect=fake_run_command):
            results = reset_eq(config)

        self.assertEqual(len(results), 10)
        self.assertTrue(all(cmd[-1] == "50%" for cmd in calls))


if __name__ == "__main__":
    unittest.main()

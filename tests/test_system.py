from __future__ import annotations

import unittest

from spotpi.system import parse_amixer_controls, parse_amixer_volume, parse_aplay_hardware


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


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import unittest
from unittest import mock

from spotpi.diagnostics import (
    check_cpu_temperature,
    cpu_percent_from_samples,
    parse_cpu_times,
)


class CpuParsingTests(unittest.TestCase):
    def test_parse_cpu_times(self) -> None:
        line = "cpu  100 0 50 800 50 0 0 0 0 0"
        parsed = parse_cpu_times(line)
        self.assertIsNotNone(parsed)
        busy, total = parsed
        self.assertEqual(total, 1000)
        self.assertEqual(busy, 150)  # total minus idle(800) minus iowait(50)

    def test_parse_cpu_times_rejects_garbage(self) -> None:
        self.assertIsNone(parse_cpu_times(""))
        self.assertIsNone(parse_cpu_times("cpu0 1 2 3 4"))
        self.assertIsNone(parse_cpu_times("cpu one two three four"))

    def test_cpu_percent_from_samples(self) -> None:
        self.assertEqual(cpu_percent_from_samples((150, 1000), (250, 1200)), 50.0)
        self.assertIsNone(cpu_percent_from_samples((150, 1000), (150, 1000)))

    def test_cpu_percent_is_clamped(self) -> None:
        self.assertEqual(cpu_percent_from_samples((100, 1000), (90, 1100)), 0.0)


class DoctorCheckTests(unittest.TestCase):
    def test_cpu_temperature_thresholds(self) -> None:
        cases = [(55.0, "ok"), (72.0, "warning"), (85.0, "error"), (None, "warning")]
        for temperature, expected in cases:
            with mock.patch("spotpi.diagnostics.cpu_temperature", return_value=temperature):
                self.assertEqual(check_cpu_temperature()["status"], expected)


if __name__ == "__main__":
    unittest.main()

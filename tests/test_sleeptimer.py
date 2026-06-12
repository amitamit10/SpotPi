from __future__ import annotations

import time
import unittest

from spotpi import sleeptimer


class SleepTimerTests(unittest.TestCase):
    def tearDown(self) -> None:
        sleeptimer.cancel()

    def test_inactive_by_default(self) -> None:
        self.assertEqual(sleeptimer.status(), {"active": False})

    def test_start_and_status(self) -> None:
        state = sleeptimer.start(60, "pause", lambda action: None)
        self.assertTrue(state["active"])
        self.assertEqual(state["action"], "pause")
        self.assertGreater(state["remaining_seconds"], 55)
        self.assertTrue(sleeptimer.status()["active"])

    def test_cancel(self) -> None:
        sleeptimer.start(60, "stop", lambda action: None)
        self.assertEqual(sleeptimer.cancel(), {"active": False})
        self.assertEqual(sleeptimer.status(), {"active": False})

    def test_fire_runs_callback_and_clears_state(self) -> None:
        fired: list[str] = []
        sleeptimer.start(0.05, "pause", fired.append)
        time.sleep(0.3)
        self.assertEqual(fired, ["pause"])
        self.assertEqual(sleeptimer.status(), {"active": False})

    def test_restart_replaces_previous_timer(self) -> None:
        fired: list[str] = []
        sleeptimer.start(60, "pause", fired.append)
        sleeptimer.start(0.05, "stop", fired.append)
        time.sleep(0.3)
        self.assertEqual(fired, ["stop"])

    def test_invalid_arguments_are_rejected(self) -> None:
        with self.assertRaises(ValueError):
            sleeptimer.start(0, "pause", lambda action: None)
        with self.assertRaises(ValueError):
            sleeptimer.start(60, "explode", lambda action: None)
        with self.assertRaises(ValueError):
            sleeptimer.start(sleeptimer.MAX_SECONDS + 1, "pause", lambda action: None)

    def test_callback_errors_do_not_leave_stale_state(self) -> None:
        def boom(action: str) -> None:
            raise RuntimeError("boom")

        sleeptimer.start(0.05, "pause", boom)
        time.sleep(0.3)
        self.assertEqual(sleeptimer.status(), {"active": False})


if __name__ == "__main__":
    unittest.main()

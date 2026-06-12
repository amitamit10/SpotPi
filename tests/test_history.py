from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from spotpi.history import clear_history, load_history, record_track


def track(name: str, track_id: str = "", **extra: str) -> dict:
    return {"name": name, "track_id": track_id, **extra}


class HistoryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "history.json"

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_record_and_load(self) -> None:
        self.assertTrue(record_track(self.path, track("Song A", "id-a", artists="Artist")))
        entries = load_history(self.path)
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["name"], "Song A")
        self.assertEqual(entries[0]["artists"], "Artist")
        self.assertIn("played_at", entries[0])

    def test_consecutive_duplicate_is_not_recorded(self) -> None:
        record_track(self.path, track("Song A", "id-a"))
        self.assertFalse(record_track(self.path, track("Song A", "id-a")))
        self.assertEqual(len(load_history(self.path)), 1)

    def test_replay_after_other_track_is_recorded(self) -> None:
        record_track(self.path, track("Song A", "id-a"))
        record_track(self.path, track("Song B", "id-b"))
        self.assertTrue(record_track(self.path, track("Song A", "id-a")))
        names = [entry["name"] for entry in load_history(self.path)]
        self.assertEqual(names, ["Song A", "Song B", "Song A"])

    def test_late_metadata_is_backfilled(self) -> None:
        record_track(self.path, track("Song A", "id-a"))
        record_track(self.path, track("Song A", "id-a", artists="Artist", cover_url="http://img"))
        entries = load_history(self.path)
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["artists"], "Artist")
        self.assertEqual(entries[0]["cover_url"], "http://img")

    def test_nameless_track_is_ignored(self) -> None:
        self.assertFalse(record_track(self.path, track("", "id-a")))
        self.assertFalse(record_track(self.path, {"event": "playing"}))
        self.assertEqual(load_history(self.path), [])

    def test_history_is_capped(self) -> None:
        for index in range(10):
            record_track(self.path, track(f"Song {index}", f"id-{index}"), max_entries=5)
        entries = load_history(self.path)
        self.assertEqual(len(entries), 5)
        self.assertEqual(entries[0]["name"], "Song 9")

    def test_clear_history(self) -> None:
        record_track(self.path, track("Song A", "id-a"))
        clear_history(self.path)
        self.assertEqual(load_history(self.path), [])
        clear_history(self.path)  # idempotent

    def test_corrupt_file_is_treated_as_empty(self) -> None:
        self.path.write_text("not json", encoding="utf-8")
        self.assertEqual(load_history(self.path), [])
        self.assertTrue(record_track(self.path, track("Song A", "id-a")))


if __name__ == "__main__":
    unittest.main()

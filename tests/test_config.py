from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from spotpi.config import ConfigError, deep_copy_defaults, list_backups, load_config, restore_backup, save_config, update_config


class ConfigTests(unittest.TestCase):
    def test_missing_config_uses_defaults(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = load_config(Path(tmp) / "missing.toml")
        self.assertEqual(config["device"]["name"], "SpotPi")
        self.assertEqual(config["web"]["auth_mode"], "none")

    def test_save_and_load_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.toml"
            config = deep_copy_defaults()
            config["backup"]["directory"] = str(Path(tmp) / "backups")
            config["device"]["name"] = "Living Room"
            config["audio"]["device_selection"] = "manual"
            config["audio"]["device"] = "hw:1,0"
            save_config(config, path)
            loaded = load_config(path)
        self.assertEqual(loaded["device"]["name"], "Living Room")
        self.assertEqual(loaded["audio"]["device"], "hw:1,0")

    def test_save_creates_restoreable_backup(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.toml"
            backup_dir = Path(tmp) / "backups"
            config = deep_copy_defaults()
            config["backup"]["directory"] = str(backup_dir)
            config["device"]["name"] = "First"
            save_config(config, path)
            config["device"]["name"] = "Second"
            save_config(config, path)
            backups = list_backups(load_config(path))
            restored = restore_backup(backups[0]["name"], load_config(path), path)
        self.assertEqual(restored["device"]["name"], "First")

    def test_update_config_merges_nested_sections(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.toml"
            save_config(deep_copy_defaults(), path)
            updated = update_config({"volume": {"startup_volume_percent": 55}}, path)
        self.assertEqual(updated["volume"]["startup_volume_percent"], 55)
        self.assertEqual(updated["quality"]["bitrate_kbps"], 320)

    def test_invalid_enum_is_rejected(self) -> None:
        config = deep_copy_defaults()
        config["audio"]["backend"] = "invalid"
        with self.assertRaises(ConfigError):
            save_config(config, Path(tempfile.gettempdir()) / "unused.toml")

    def test_unknown_key_is_rejected(self) -> None:
        config = deep_copy_defaults()
        config["device"]["surprise"] = True
        with self.assertRaises(ConfigError):
            save_config(config, Path(tempfile.gettempdir()) / "unused.toml")


if __name__ == "__main__":
    unittest.main()

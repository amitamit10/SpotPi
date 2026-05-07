from __future__ import annotations

import unittest

from spotpi.config import deep_copy_defaults
from spotpi.librespot import build_librespot_args, redacted_args, resolved_device_name


class LibrespotTests(unittest.TestCase):
    def test_default_args_include_stable_audio_settings(self) -> None:
        config = deep_copy_defaults()
        args = build_librespot_args(config)
        self.assertIn("--name", args)
        self.assertIn("SpotPi", args)
        self.assertIn("--backend", args)
        self.assertIn("alsa", args)
        self.assertIn("--bitrate", args)
        self.assertIn("320", args)
        self.assertIn("--enable-volume-normalisation", args)

    def test_manual_alsa_device_is_included(self) -> None:
        config = deep_copy_defaults()
        config["audio"]["device_selection"] = "manual"
        config["audio"]["device"] = "hw:1,0"
        args = build_librespot_args(config)
        device_index = args.index("--device")
        self.assertEqual(args[device_index + 1], "hw:1,0")

    def test_access_token_is_redacted(self) -> None:
        config = deep_copy_defaults()
        config["librespot"]["access_token"] = "secret-token"
        args = redacted_args(build_librespot_args(config))
        self.assertNotIn("secret-token", args)
        self.assertIn("REDACTED", args)

    def test_hostname_suffix_is_optional(self) -> None:
        config = deep_copy_defaults()
        self.assertEqual(resolved_device_name(config), "SpotPi")
        config["device"]["append_hostname"] = True
        self.assertTrue(resolved_device_name(config).startswith("SpotPi ("))


if __name__ == "__main__":
    unittest.main()

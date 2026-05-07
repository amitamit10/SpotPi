"""Command line utilities for installation checks and support."""

from __future__ import annotations

import argparse
import json
import shlex
import sys

from .config import default_config_path, list_backups, load_config, save_config
from .diagnostics import doctor
from .librespot import build_librespot_args, redacted_args


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="spotpi")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("doctor", help="Run health checks")
    subparsers.add_parser("config-path", help="Print active config path")
    subparsers.add_parser("init-config", help="Create config if missing")
    subparsers.add_parser("backups", help="List config backups")
    subparsers.add_parser("preview", help="Print the generated librespot command")
    args = parser.parse_args(argv)

    if args.command == "config-path":
        print(default_config_path())
        return 0
    if args.command == "init-config":
        path = default_config_path()
        if path.exists():
            print(path)
            return 0
        save_config(load_config(path), path)
        print(path)
        return 0
    if args.command == "backups":
        print(json.dumps(list_backups(load_config()), indent=2))
        return 0
    if args.command == "preview":
        config = load_config()
        print(shlex.join(redacted_args(build_librespot_args(config))))
        return 0
    if args.command == "doctor":
        report = doctor(load_config())
        print(json.dumps(report, indent=2))
        return 0 if report["summary"]["error"] == 0 else 2
    return 1


def doctor_main() -> int:
    return main(["doctor"])


def init_config_main() -> int:
    return main(["init-config"])


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

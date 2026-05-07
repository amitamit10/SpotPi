"""Small HTTP server for the local settings UI."""

from __future__ import annotations

import json
import mimetypes
import shlex
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from . import __version__
from .config import ConfigError, default_config_path, list_backups, load_config, restore_backup, save_config, schema_payload
from .diagnostics import doctor, system_summary
from .librespot import build_librespot_args, redacted_args
from .profiles import delete_profile, list_profiles, load_profile, save_profile
from .system import (
    journal_logs_for_target,
    list_audio_devices,
    mixer_state,
    set_mixer_volume,
    status_payload,
    systemctl_target,
    test_sound,
)

STATIC_DIR = Path(__file__).with_name("static")


class ApiError(Exception):
    def __init__(self, status: HTTPStatus, message: str):
        self.status = status
        self.message = message
        super().__init__(message)


class RequestHandler(BaseHTTPRequestHandler):
    server_version = f"SpotPi/{__version__}"

    def do_GET(self) -> None:
        self.dispatch("GET")

    def do_POST(self) -> None:
        self.dispatch("POST")

    def do_PUT(self) -> None:
        self.dispatch("PUT")

    def do_DELETE(self) -> None:
        self.dispatch("DELETE")

    def log_message(self, fmt: str, *args: Any) -> None:
        print(f"{self.address_string()} - {fmt % args}")

    def dispatch(self, method: str) -> None:
        parsed = urlparse(self.path)
        try:
            if parsed.path.startswith("/api/"):
                self.ensure_authorized(parsed.path)
                payload = self.handle_api(method, parsed.path, parse_qs(parsed.query))
                self.send_json(payload)
                return
            self.serve_static(parsed.path)
        except ApiError as exc:
            self.send_json({"error": exc.message}, status=exc.status)
        except ConfigError as exc:
            self.send_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
        except ValueError as exc:
            self.send_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
        except Exception as exc:  # pragma: no cover - final safety net for the UI
            self.send_json({"error": str(exc)}, status=HTTPStatus.INTERNAL_SERVER_ERROR)

    def ensure_authorized(self, path: str) -> None:
        if path == "/api/schema":
            return
        config = load_config()
        web = config["web"]
        if web["auth_mode"] == "none":
            return
        if web["auth_mode"] == "pin" and self.headers.get("X-SpotPi-Pin") == web["auth_pin"]:
            return
        raise ApiError(HTTPStatus.UNAUTHORIZED, "Unauthorized")

    def handle_api(self, method: str, path: str, query: dict[str, list[str]]) -> dict[str, Any]:
        config = load_config()
        if method == "GET" and path == "/api/schema":
            return schema_payload()
        if method == "GET" and path == "/api/settings":
            return {"config": config, "path": str(default_config_path())}
        if method == "PUT" and path == "/api/settings":
            payload = self.read_json()
            saved = save_config(payload.get("config", payload))
            return {"config": saved, "path": str(default_config_path())}
        if method == "GET" and path == "/api/status":
            return status_payload(config)
        if method == "GET" and path == "/api/system":
            return system_summary(config)
        if method == "GET" and path == "/api/doctor":
            return doctor(config)
        if method == "GET" and path == "/api/audio/devices":
            return list_audio_devices(config)
        if method == "GET" and path == "/api/audio/mixer":
            return mixer_state(config)
        if method == "POST" and path == "/api/audio/volume":
            payload = self.read_json()
            return set_mixer_volume(config, int(payload.get("percent", 0))).as_dict()
        if method == "GET" and path == "/api/logs":
            lines = int(query.get("lines", [config["diagnostics"]["log_lines"]])[0])
            target = query.get("target", ["spotify"])[0]
            result = journal_logs_for_target(config, target, lines)
            return result.as_dict()
        if method == "POST" and path.startswith("/api/service/"):
            parts = path.strip("/").split("/")
            if len(parts) == 3:
                _, _, action = parts
                target = "spotify"
            elif len(parts) == 4:
                _, _, target, action = parts
            else:
                raise ApiError(HTTPStatus.NOT_FOUND, "Not found")
            result = systemctl_target(config, action, target)
            return result.as_dict()
        if method == "POST" and path == "/api/diagnostics/test-sound":
            return test_sound(config).as_dict()
        if method == "GET" and path == "/api/librespot/preview":
            args = redacted_args(build_librespot_args(config, include_executable=True))
            return {"args": args, "command": shlex.join(args)}
        if method == "GET" and path == "/api/backups":
            return {"backups": list_backups(config)}
        if method == "POST" and path == "/api/backups/restore":
            payload = self.read_json()
            return {"config": restore_backup(str(payload.get("name", "")), config)}
        if method == "GET" and path == "/api/profiles":
            return {"profiles": list_profiles(config)}
        if method == "POST" and path == "/api/profiles/save":
            payload = self.read_json()
            return save_profile(config, payload.get("name", "profile"), payload.get("config"))
        if method == "POST" and path == "/api/profiles/load":
            payload = self.read_json()
            return {"config": load_profile(config, payload.get("name", ""))}
        if method == "DELETE" and path.startswith("/api/profiles/"):
            name = path.rsplit("/", 1)[-1]
            return delete_profile(config, name)
        raise ApiError(HTTPStatus.NOT_FOUND, "Not found")

    def read_json(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0"))
        if length == 0:
            return {}
        raw = self.rfile.read(length)
        try:
            data = json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError as exc:
            raise ApiError(HTTPStatus.BAD_REQUEST, f"Invalid JSON: {exc}") from exc
        if not isinstance(data, dict):
            raise ApiError(HTTPStatus.BAD_REQUEST, "JSON body must be an object")
        return data

    def send_json(self, payload: dict[str, Any], status: HTTPStatus = HTTPStatus.OK) -> None:
        body = json.dumps(payload, indent=2, sort_keys=True).encode("utf-8")
        self.send_response(status.value)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def serve_static(self, path: str) -> None:
        relative = "index.html" if path in {"", "/"} else path.lstrip("/")
        target = (STATIC_DIR / relative).resolve()
        if STATIC_DIR.resolve() not in target.parents and target != STATIC_DIR.resolve():
            raise ApiError(HTTPStatus.FORBIDDEN, "Forbidden")
        if not target.exists() or not target.is_file():
            raise ApiError(HTTPStatus.NOT_FOUND, "Not found")
        content = target.read_bytes()
        self.send_response(HTTPStatus.OK.value)
        self.send_header("Content-Type", mimetypes.guess_type(str(target))[0] or "application/octet-stream")
        self.send_header("Content-Length", str(len(content)))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(content)


def main() -> None:
    config = load_config()
    host = config["web"]["host"]
    port = int(config["web"]["port"])
    server = ThreadingHTTPServer((host, port), RequestHandler)
    print(f"SpotPi UI listening on http://{host}:{port}")
    server.serve_forever()

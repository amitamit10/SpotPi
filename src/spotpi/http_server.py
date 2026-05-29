"""Small HTTP server for the local settings UI."""

from __future__ import annotations

import glob
import json
import mimetypes
import re
import shlex
import shutil
import subprocess
import urllib.request
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

_JOURNAL_TRACK_RE = re.compile(r"Loading <(.+?)> with Spotify URI <(spotify:track:(\w+))>")
_OG_RE = re.compile(r'<meta[^>]+property=["\']og:(\w+)["\']\s+content=["\'](.*?)["\']')
_HTML_ENTITIES = {"&#x27;": "'", "&amp;": "&", "&quot;": '"', "&lt;": "<", "&gt;": ">"}
_spotify_meta_cache: dict[str, dict[str, str]] = {}


def _journal_track(config: dict[str, Any]) -> tuple[str, str]:
    """Return (name, track_id) of the most recently loaded track from journal logs."""
    try:
        service = config["service"]["spotify_service_name"]
        result = subprocess.run(
            ["journalctl", "-u", service, "-n", "200", "--no-pager", "--output=cat"],
            text=True, capture_output=True, timeout=5,
        )
        matches = _JOURNAL_TRACK_RE.findall(result.stdout)
        if matches:
            name, _uri, track_id = matches[-1]
            return name, track_id
    except Exception:
        pass
    return "", ""


def _fetch_spotify_meta(track_id: str) -> dict[str, str]:
    """Fetch track name, artist, album and cover from Spotify open-graph tags.

    Results are cached in memory for the server's lifetime so each track
    only triggers one outbound request.
    """
    if track_id in _spotify_meta_cache:
        return _spotify_meta_cache[track_id]
    try:
        url = f"https://open.spotify.com/track/{track_id}"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (compatible; Googlebot/2.1)"})
        with urllib.request.urlopen(req, timeout=4) as resp:
            html = resp.read().decode("utf-8", errors="replace")
        og: dict[str, str] = {}
        for m in _OG_RE.finditer(html):
            val = m.group(2)
            for ent, ch in _HTML_ENTITIES.items():
                val = val.replace(ent, ch)
            og[m.group(1)] = val
        # og:description format: "Artist · Album · Song · Year"
        parts = [p.strip() for p in og.get("description", "").split("·")]
        meta = {
            "name":      og.get("title", ""),
            "artists":   parts[0] if parts and parts[0] else "",
            "album":     parts[1] if len(parts) > 1 else "",
            "cover_url": og.get("image", ""),
        }
        _spotify_meta_cache[track_id] = meta
        return meta
    except Exception:
        return {}


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
        if method == "GET" and path == "/api/nowplaying":
            # Both services use PrivateTmp=true so /tmp is not shared between
            # them. Use /var/lib/<service-name>/ which is in ReadWritePaths.
            service_name = default_config_path().parent.name
            data: dict[str, Any] = {"event": "unknown"}
            for candidate in [
                Path("/var/lib") / service_name / "nowplaying.json",
                Path("/tmp/spotpi-nowplaying.json"),
            ]:
                if candidate.exists():
                    try:
                        data = json.loads(candidate.read_text())
                        break
                    except Exception:
                        pass
            # If the track name is missing (happens when librespot fires a
            # "playing" event on startup without metadata), fall back to the
            # most recent "Loading <name>" line in the service journal.
            if not data.get("name") and data.get("event") != "unknown":
                name, track_id = _journal_track(config)
                if name:
                    data["name"] = name
                    if not data.get("track_id") and track_id:
                        data["track_id"] = track_id
            # Enrich missing artist / cover_url from Spotify open-graph tags.
            # Fetched once per track_id and cached for the server's lifetime.
            tid = data.get("track_id", "")
            if tid and data.get("event") not in ("unknown", "stopped", "session_disconnected"):
                if not data.get("artists") or not data.get("cover_url"):
                    meta = _fetch_spotify_meta(tid)
                    if not data.get("name") and meta.get("name"):
                        data["name"] = meta["name"]
                    if not data.get("artists") and meta.get("artists"):
                        data["artists"] = meta["artists"]
                    if not data.get("album") and meta.get("album"):
                        data["album"] = meta["album"]
                    if not data.get("cover_url") and meta.get("cover_url"):
                        data["cover_url"] = meta["cover_url"]
            return data
        if method == "POST" and path == "/api/update":
            return self._run_update()
        raise ApiError(HTTPStatus.NOT_FOUND, "Not found")

    def _run_update(self) -> dict[str, Any]:
        # Find git repo using `find` (avoids permission issues with glob on /home/*)
        find_result = subprocess.run(
            ["find", "/home", "/root", "/opt", "-maxdepth", "4", "-name", ".git", "-type", "d"],
            text=True, capture_output=True, timeout=15,
        )
        repo: Path | None = None
        for git_dir in find_result.stdout.splitlines():
            candidate = Path(git_dir).parent
            if candidate.name in ("pi-connect-speaker", "spotpi"):
                repo = candidate
                break

        if repo is None:
            raise ApiError(HTTPStatus.INTERNAL_SERVER_ERROR,
                           "Git repository not found. Clone the repo to your home directory first.")

        result = subprocess.run(
            ["git", "-C", str(repo), "pull", "origin", "main"],
            text=True, capture_output=True, timeout=60,
        )
        pull_output = (result.stdout + result.stderr).strip()
        if result.returncode != 0:
            raise ApiError(HTTPStatus.INTERNAL_SERVER_ERROR, pull_output or "git pull failed")

        # Find installed package dir
        pkg: Path | None = None
        for name in ("pi_connect_speaker", "spotpi"):
            for venv_root in ("/opt/pi-connect-speaker/venv", "/opt/spotpi/venv"):
                matches = glob.glob(f"{venv_root}/lib/python*/site-packages/{name}")
                if matches:
                    pkg = Path(matches[0])
                    break
            if pkg:
                break

        copied: list[str] = []
        if pkg:
            src_dir: Path | None = None
            for name in ("spotpi", "pi_connect_speaker"):
                candidate = repo / "src" / name
                if candidate.is_dir():
                    src_dir = candidate
                    break
            if src_dir:
                for pyfile in src_dir.glob("*.py"):
                    try:
                        shutil.copy2(pyfile, pkg / pyfile.name)
                        copied.append(pyfile.name)
                    except OSError:
                        pass
                static_src = src_dir / "static"
                static_dst = pkg / "static"
                if static_src.is_dir():
                    for f in static_src.rglob("*"):
                        if f.is_file():
                            rel = f.relative_to(static_src)
                            dst = static_dst / rel
                            try:
                                dst.parent.mkdir(parents=True, exist_ok=True)
                                shutil.copy2(f, dst)
                                copied.append(f"static/{rel}")
                            except OSError:
                                pass
            event_src = repo / "scripts" / "spotpi-event"
            if event_src.exists():
                try:
                    shutil.copy2(event_src, "/usr/local/bin/spotpi-event")
                    Path("/usr/local/bin/spotpi-event").chmod(0o755)
                    copied.append("spotpi-event")
                except OSError:
                    pass

        # Restart services in background after response is sent
        config = load_config()
        svc = config["service"]["spotify_service_name"]
        web_svc = config["service"]["web_service_name"]
        subprocess.Popen(
            ["bash", "-c",
             f"sleep 2 && systemctl restart {svc} {web_svc} 2>/dev/null"
             f" || sudo systemctl restart {svc} {web_svc} 2>/dev/null"],
            start_new_session=True,
        )
        return {"ok": True, "output": pull_output, "copied": copied, "restarting": True}

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

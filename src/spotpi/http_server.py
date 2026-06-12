"""Small HTTP server for the local settings UI."""

from __future__ import annotations

import base64
import glob
import hashlib
import hmac
import json
import mimetypes
import os
import re
import secrets
import shlex
import shutil
import subprocess
import threading
import time
import html as html_module
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from . import __version__, sleeptimer
from .config import (
    ConfigError,
    default_config_path,
    dumps_toml,
    import_config_text,
    list_backups,
    load_config,
    restore_backup,
    save_config,
    schema_payload,
)
from .diagnostics import doctor, system_summary
from .history import clear_history, history_file, load_history, record_track
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
_SERVER_STARTED = time.monotonic()

mimetypes.add_type("application/manifest+json", ".webmanifest")
mimetypes.add_type("image/svg+xml", ".svg")

_JOURNAL_TRACK_RE = re.compile(r"Loading <(.+?)> with Spotify URI <(spotify:track:(\w+))>")
_JOURNAL_VOL_RE = re.compile(r"volume is now (\d+)")
_last_ui_vol_ts: float = 0.0   # monotonic timestamp of last web-UI volume set


def _stamp_ui_vol() -> None:
    global _last_ui_vol_ts
    _last_ui_vol_ts = time.monotonic()


# ---------------------------------------------------------------------------
# Spotify Web API helpers (server-side PKCE + token proxy)
# ---------------------------------------------------------------------------
_SP_TOKEN_FILE = Path("/var/lib/pi-connect-speaker/spotify_token.json")
_SP_STATE_FILE = Path("/var/lib/pi-connect-speaker/spotify_pkce_state.json")
_SP_SCOPES = (
    "user-read-playback-state user-modify-playback-state "
    "user-read-currently-playing user-library-read user-library-modify"
)
_SP_TRACK_ID_RE = re.compile(r"^[A-Za-z0-9]{1,40}$")


def _sp_token_file() -> Path:
    """Return the token path under the correct service data dir."""
    service_name = default_config_path().parent.name
    return Path("/var/lib") / service_name / "spotify_token.json"


def _sp_state_file() -> Path:
    service_name = default_config_path().parent.name
    return Path("/var/lib") / service_name / "spotify_pkce_state.json"


def _sp_make_auth_url(client_id: str, redirect_uri: str) -> dict[str, str]:
    """Generate a PKCE auth URL server-side (crypto.subtle not available on HTTP)."""
    verifier = secrets.token_urlsafe(48)
    digest = hashlib.sha256(verifier.encode()).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode()
    state = secrets.token_urlsafe(16)
    _sp_state_file().parent.mkdir(parents=True, exist_ok=True)
    _sp_state_file().write_text(json.dumps({"verifier": verifier, "state": state, "redirect_uri": redirect_uri}))
    params = urllib.parse.urlencode({
        "client_id": client_id,
        "response_type": "code",
        "redirect_uri": redirect_uri,
        "code_challenge_method": "S256",
        "code_challenge": challenge,
        "state": state,
        "scope": _SP_SCOPES,
    })
    return {"url": f"https://accounts.spotify.com/authorize?{params}"}


def _sp_exchange_code(code: str) -> dict[str, Any]:
    """Exchange an auth code for tokens using the stored PKCE verifier."""
    sf = _sp_state_file()
    if not sf.exists():
        raise ApiError(HTTPStatus.BAD_REQUEST, "No PKCE state found — start auth again")
    state = json.loads(sf.read_text())
    body = urllib.parse.urlencode({
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": state["redirect_uri"],
        "client_id": _sp_client_id(),
        "code_verifier": state["verifier"],
    }).encode()
    req = urllib.request.Request(
        "https://accounts.spotify.com/api/token",
        data=body,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            token = json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise ApiError(HTTPStatus.BAD_GATEWAY, f"Spotify token exchange failed: {body}") from exc
    except urllib.error.URLError as exc:
        raise ApiError(HTTPStatus.BAD_GATEWAY, f"Could not reach Spotify: {exc.reason}") from exc
    token["expires_at"] = int(time.time()) + int(token.get("expires_in", 3600))
    _sp_token_file().parent.mkdir(parents=True, exist_ok=True)
    _sp_token_file().write_text(json.dumps(token))
    sf.unlink(missing_ok=True)
    return {"ok": True}


def _sp_client_id() -> str:
    try:
        return load_config()["web"]["spotify_client_id"]
    except Exception:
        return ""


def _sp_access_token() -> str:
    """Return a valid access token, refreshing if needed."""
    tf = _sp_token_file()
    if not tf.exists():
        raise ApiError(HTTPStatus.UNAUTHORIZED, "Not connected to Spotify — use Connect Spotify")
    token = json.loads(tf.read_text())
    if int(time.time()) < token.get("expires_at", 0) - 60:
        return token["access_token"]
    # Refresh
    body = urllib.parse.urlencode({
        "grant_type": "refresh_token",
        "refresh_token": token["refresh_token"],
        "client_id": _sp_client_id(),
    }).encode()
    req = urllib.request.Request(
        "https://accounts.spotify.com/api/token",
        data=body,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            refreshed = json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise ApiError(HTTPStatus.BAD_GATEWAY, f"Spotify token refresh failed: {body}") from exc
    except urllib.error.URLError as exc:
        raise ApiError(HTTPStatus.BAD_GATEWAY, f"Could not reach Spotify: {exc.reason}") from exc
    refreshed["expires_at"] = int(time.time()) + int(refreshed.get("expires_in", 3600))
    if "refresh_token" not in refreshed:
        refreshed["refresh_token"] = token["refresh_token"]
    _sp_token_file().write_text(json.dumps(refreshed))
    return refreshed["access_token"]


def _sp_api(path: str, method: str = "GET", body: dict[str, Any] | None = None) -> dict[str, Any]:
    """Call the Spotify Web API and return parsed JSON (or {} for 204)."""
    access = _sp_access_token()
    headers = {"Authorization": f"Bearer {access}"}
    data = None
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(
        f"https://api.spotify.com/v1{path}",
        method=method,
        headers=headers,
        data=data,
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            raw = resp.read()
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:
        if exc.code == 204:
            return {}
        # Surface Spotify's own error message (e.g. "No active device found")
        detail = ""
        try:
            payload = json.loads(exc.read().decode("utf-8", errors="replace"))
            detail = payload.get("error", {}).get("message", "")
        except Exception:
            pass
        if exc.code == 404 and not detail:
            detail = "No active playback device"
        message = f"Spotify: {detail}" if detail else f"Spotify API error {exc.code}"
        raise ApiError(HTTPStatus.BAD_GATEWAY, message) from exc
    except urllib.error.URLError as exc:
        raise ApiError(HTTPStatus.BAD_GATEWAY, f"Could not reach Spotify: {exc.reason}") from exc


def _sp_player_state() -> dict[str, Any]:
    """Compact subset of the Spotify player state for the dashboard."""
    data = _sp_api("/me/player")
    if not data:
        return {"active": False}
    item = data.get("item") or {}
    device = data.get("device") or {}
    return {
        "active": True,
        "is_playing": bool(data.get("is_playing")),
        "shuffle": bool(data.get("shuffle_state")),
        "repeat": data.get("repeat_state", "off"),
        "progress_ms": data.get("progress_ms") or 0,
        "duration_ms": item.get("duration_ms") or 0,
        "track": item.get("name", ""),
        "track_id": item.get("id") or "",
        "device": device.get("name", ""),
        "volume_percent": device.get("volume_percent"),
    }


_OG_RE = re.compile(r'<meta[^>]+property=["\']og:(\w+)["\']\s+content=["\'](.*?)["\']')
_HTML_ENTITIES = {"&#x27;": "'", "&amp;": "&", "&quot;": '"', "&lt;": "<", "&gt;": ">"}
_spotify_meta_cache: dict[str, dict[str, str]] = {}
_META_CACHE_MAX = 256  # bound memory on an always-on device


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


def _journal_spotify_volume(config: dict[str, Any]) -> int | None:
    """Return the most recent Spotify volume (0-100) from the librespot journal."""
    try:
        service = config["service"]["spotify_service_name"]
        result = subprocess.run(
            ["journalctl", "-u", service, "-n", "100", "--no-pager", "--output=cat"],
            text=True, capture_output=True, timeout=5,
        )
        matches = _JOURNAL_VOL_RE.findall(result.stdout)
        if matches:
            return round(int(matches[-1]) / 65535 * 100)
    except Exception:
        pass
    return None


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
        while len(_spotify_meta_cache) >= _META_CACHE_MAX:
            _spotify_meta_cache.pop(next(iter(_spotify_meta_cache)))
        _spotify_meta_cache[track_id] = meta
        return meta
    except Exception:
        return {}


class ApiError(Exception):
    def __init__(self, status: HTTPStatus, message: str):
        self.status = status
        self.message = message
        super().__init__(message)


def _find_repo() -> Path | None:
    """Locate the cloned SpotPi repository (uses find to dodge /home perms)."""
    result = subprocess.run(
        ["find", "/home", "/root", "/opt", "-maxdepth", "4", "-name", ".git", "-type", "d"],
        text=True, capture_output=True, timeout=15,
    )
    for git_dir in result.stdout.splitlines():
        candidate = Path(git_dir).parent
        if candidate.name in ("pi-connect-speaker", "spotpi"):
            return candidate
    return None


def _check_update() -> dict[str, Any]:
    """Fetch origin/main and report how many commits the install is behind."""
    repo = _find_repo()
    if repo is None:
        return {"available": False, "error": "Git repository not found"}
    fetch = subprocess.run(
        ["git", "-C", str(repo), "fetch", "--quiet", "origin", "main"],
        text=True, capture_output=True, timeout=30,
    )
    if fetch.returncode != 0:
        return {"available": False, "error": (fetch.stderr or "git fetch failed").strip()}
    count = subprocess.run(
        ["git", "-C", str(repo), "rev-list", "--count", "HEAD..origin/main"],
        text=True, capture_output=True, timeout=10,
    )
    try:
        behind = int(count.stdout.strip())
    except ValueError:
        return {"available": False, "error": (count.stderr or "rev-list failed").strip()}
    return {"available": behind > 0, "behind": behind}


def _sleep_timer_fire(action: str) -> None:
    """Executed by the sleep timer thread when the countdown ends."""
    config = load_config()
    if action == "pause":
        try:
            _sp_api("/me/player/pause", "PUT")
            return
        except Exception:
            # Not connected to the Web API (or no active device) — fall back
            # to stopping the engine so the speaker still goes quiet.
            pass
    systemctl_target(config, "stop", "spotify")


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
            # Spotify OAuth callback: redirected here after the user authorises
            if method == "GET" and parsed.path == "/" and "code" in parse_qs(parsed.query):
                self._handle_oauth_callback(parse_qs(parsed.query))
                return
            if parsed.path.startswith("/api/"):
                self.ensure_authorized(parsed.path)
                if method == "GET" and parsed.path == "/api/settings/export":
                    self._send_config_export()
                    return
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

    def _handle_oauth_callback(self, query: dict[str, list[str]]) -> None:
        code = (query.get("code") or [None])[0]
        state = (query.get("state") or [None])[0]
        sf = _sp_state_file()
        if not code or not state or not sf.exists():
            self.serve_static("/")
            return
        stored = json.loads(sf.read_text())
        if stored.get("state") != state:
            self.serve_static("/")
            return
        try:
            _sp_exchange_code(code)
            html = (
                "<html><head><title>SpotPi — Spotify Connected</title>"
                "<style>body{font-family:sans-serif;text-align:center;padding:60px;"
                "background:#0d0d0d;color:#fff}h2{color:#1db954}p{color:#aaa}a{color:#1db954}</style></head>"
                "<body><h2>Spotify account connected!</h2>"
                "<p>Redirecting back to SpotPi&hellip;</p>"
                "<a href='/'>Back to SpotPi</a>"
                "<script>setTimeout(()=>{window.location.href='/'},2500)</script>"
                "</body></html>"
            )
        except Exception as exc:
            html = (
                "<html><head><title>SpotPi — Error</title>"
                "<style>body{font-family:sans-serif;text-align:center;padding:60px;"
                "background:#0d0d0d;color:#fff}h2{color:#e74c3c}p{color:#aaa}a{color:#1db954}</style></head>"
                f"<body><h2>Error connecting Spotify</h2>"
                f"<p>{html_module.escape(str(exc))}</p>"
                "<a href='/'>Back to SpotPi</a></body></html>"
            )
        body = html.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def ensure_authorized(self, path: str) -> None:
        if path in {"/api/schema", "/api/health"}:
            return
        config = load_config()
        web = config["web"]
        if web["auth_mode"] == "none":
            return
        if web["auth_mode"] == "pin":
            # An empty PIN cannot protect anything; treat it as auth disabled
            # instead of locking the user out of their own device.
            if not web["auth_pin"]:
                return
            supplied = self.headers.get("X-SpotPi-Pin", "")
            if hmac.compare_digest(supplied, web["auth_pin"]):
                return
        raise ApiError(HTTPStatus.UNAUTHORIZED, "Unauthorized")

    def handle_api(self, method: str, path: str, query: dict[str, list[str]]) -> dict[str, Any]:
        config = load_config()
        if method == "GET" and path == "/api/schema":
            return schema_payload()
        if method == "GET" and path == "/api/health":
            return {
                "ok": True,
                "version": __version__,
                "uptime_seconds": round(time.monotonic() - _SERVER_STARTED, 1),
            }
        if method == "GET" and path == "/api/settings":
            return {"config": config, "path": str(default_config_path())}
        if method == "PUT" and path == "/api/settings":
            payload = self.read_json()
            saved = save_config(payload.get("config", payload))
            return {"config": saved, "path": str(default_config_path())}
        if method == "POST" and path == "/api/settings/import":
            payload = self.read_json()
            toml_text = str(payload.get("toml", ""))
            if not toml_text.strip():
                raise ApiError(HTTPStatus.BAD_REQUEST, "TOML content required")
            saved = import_config_text(toml_text)
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
            state = mixer_state(config)
            # Sync ALSA control from Spotify journal when the web UI
            # hasn't touched volume in the last 10 s.
            if time.monotonic() - _last_ui_vol_ts > 10:
                spotify_vol = _journal_spotify_volume(config)
                if spotify_vol is not None:
                    current = state.get("volume_percent") or 0
                    if abs(current - spotify_vol) > 2:
                        set_mixer_volume(config, spotify_vol)
                        state["volume_percent"] = spotify_vol
            return state
        if method == "POST" and path == "/api/audio/volume":
            payload = self.read_json()
            _stamp_ui_vol()
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
            # Estimate the live position from the event timestamp so the UI
            # can show progress without a Spotify Web API connection. Both
            # timestamps are Pi-local, so browser clock skew is irrelevant.
            if data.get("event") in ("playing", "changed", "started") and data.get("duration_ms"):
                try:
                    elapsed_ms = int((datetime.now() - datetime.fromisoformat(str(data.get("ts", "")))).total_seconds() * 1000)
                    if elapsed_ms >= 0:
                        data["position_estimate_ms"] = min(
                            int(data.get("position_ms", 0) or 0) + elapsed_ms,
                            int(data["duration_ms"]),
                        )
                except (ValueError, TypeError):
                    pass
            # Record into the recently-played history (deduped against the
            # newest entry, so the 2 s polling loop is harmless).
            if data.get("event") in ("playing", "changed", "started") and data.get("name"):
                try:
                    record_track(history_file(service_name), data)
                except OSError:
                    pass
            return data
        if method == "GET" and path == "/api/history":
            service_name = default_config_path().parent.name
            return {"tracks": load_history(history_file(service_name))}
        if method == "DELETE" and path == "/api/history":
            service_name = default_config_path().parent.name
            clear_history(history_file(service_name))
            return {"ok": True}
        if method == "GET" and path == "/api/sleep-timer":
            return sleeptimer.status()
        if method == "POST" and path == "/api/sleep-timer":
            payload = self.read_json()
            try:
                minutes = float(payload.get("minutes", 0))
            except (TypeError, ValueError):
                raise ApiError(HTTPStatus.BAD_REQUEST, "minutes must be a number") from None
            action = str(payload.get("action", "pause"))
            return sleeptimer.start(minutes * 60, action, _sleep_timer_fire)
        if method == "DELETE" and path == "/api/sleep-timer":
            return sleeptimer.cancel()
        if method == "POST" and path == "/api/update":
            return self._run_update()
        if method == "GET" and path == "/api/update/check":
            return _check_update()
        # Spotify Web API proxy (server-side PKCE so crypto.subtle isn't needed on HTTP)
        if method == "GET" and path == "/api/spotify/auth-url":
            client_id = config["web"]["spotify_client_id"]
            if not client_id:
                raise ApiError(HTTPStatus.BAD_REQUEST, "Set a Spotify Client ID in Advanced → Web UI settings first")
            redirect_uri = query.get("redirect_uri", [""])[0]
            if not redirect_uri:
                raise ApiError(HTTPStatus.BAD_REQUEST, "redirect_uri required")
            return _sp_make_auth_url(client_id, redirect_uri)
        if method == "POST" and path == "/api/spotify/callback":
            payload = self.read_json()
            return _sp_exchange_code(str(payload.get("code", "")))
        if method == "GET" and path == "/api/spotify/status":
            try:
                _sp_access_token()
                return {"connected": True}
            except ApiError:
                return {"connected": False}
        if method == "POST" and path == "/api/spotify/next":
            return _sp_api("/me/player/next", "POST")
        if method == "POST" and path == "/api/spotify/previous":
            return _sp_api("/me/player/previous", "POST")
        if method == "GET" and path == "/api/spotify/queue":
            return _sp_api("/me/player/queue")
        if method == "GET" and path == "/api/spotify/player":
            return _sp_player_state()
        if method == "POST" and path == "/api/spotify/play":
            return _sp_api("/me/player/play", "PUT")
        if method == "POST" and path == "/api/spotify/pause":
            return _sp_api("/me/player/pause", "PUT")
        if method == "POST" and path == "/api/spotify/shuffle":
            payload = self.read_json()
            shuffle_state = "true" if payload.get("state") else "false"
            return _sp_api(f"/me/player/shuffle?state={shuffle_state}", "PUT")
        if method == "POST" and path == "/api/spotify/repeat":
            payload = self.read_json()
            repeat_state = str(payload.get("state", "off"))
            if repeat_state not in {"off", "context", "track"}:
                raise ApiError(HTTPStatus.BAD_REQUEST, "state must be off, context or track")
            return _sp_api(f"/me/player/repeat?state={repeat_state}", "PUT")
        if method == "GET" and path == "/api/spotify/saved":
            track_id = query.get("id", [""])[0]
            if not _SP_TRACK_ID_RE.match(track_id):
                raise ApiError(HTTPStatus.BAD_REQUEST, "Invalid track id")
            result = _sp_api(f"/me/tracks/contains?ids={track_id}")
            saved = bool(result[0]) if isinstance(result, list) and result else False
            return {"id": track_id, "saved": saved}
        if method == "POST" and path == "/api/spotify/save":
            payload = self.read_json()
            track_id = str(payload.get("id", ""))
            if not _SP_TRACK_ID_RE.match(track_id):
                raise ApiError(HTTPStatus.BAD_REQUEST, "Invalid track id")
            wanted = bool(payload.get("saved", True))
            _sp_api(f"/me/tracks?ids={track_id}", "PUT" if wanted else "DELETE")
            return {"id": track_id, "saved": wanted}
        raise ApiError(HTTPStatus.NOT_FOUND, "Not found")

    def _run_update(self) -> dict[str, Any]:
        repo = _find_repo()
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

    def _send_config_export(self) -> None:
        body = dumps_toml(load_config()).encode("utf-8")
        filename = f"spotpi-config-{time.strftime('%Y%m%d-%H%M%S')}.toml"
        self.send_response(HTTPStatus.OK.value)
        self.send_header("Content-Type", "application/toml; charset=utf-8")
        self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

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

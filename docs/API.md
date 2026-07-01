# API

The web UI uses a small JSON API. Default host and port:

```text
http://<raspberry-pi-ip>:8080
```

## Authentication

`GET /api/schema` and `GET /api/health` are always public. All other
endpoints are gated by `web.auth_mode`:

- `none` (default) — no auth required.
- `pin` — send the configured PIN in the `X-SpotPi-Pin` header. An empty PIN
  is treated as auth disabled.

Independent of `auth_mode`, if `web.api_key` is set in settings, any request
carrying `X-Api-Key: <key>` is authorized. This is meant for programmatic
clients (e.g. an AI assistant) so they don't need the PIN shared with the
web UI.

## Settings

`GET /api/schema`

Returns editable sections and fields.

`GET /api/settings`

Returns the active validated config.

`PUT /api/settings`

Writes the full config. The body can be either the config object or `{ "config": ... }`.

`GET /api/settings/export`

Downloads the active config as a timestamped `.toml` attachment.

`POST /api/settings/import`

Validates and saves configuration supplied as TOML text. The previous config is backed up automatically (when backups are enabled).

```json
{ "toml": "[device]\nname = \"SpotPi\"\n..." }
```

## Health

`GET /api/health`

Liveness endpoint (no authentication required). Returns `ok`, `version`, and `uptime_seconds` of the web server process.

## Status and Doctor

`GET /api/status`

Returns service state, generated librespot command, device name, and key paths.

`GET /api/system`

Returns hostname, IP addresses, platform, uptime, temperature, CPU usage (`cpu_percent`), load average, memory (including `used_percent`), and disk summary.

`GET /api/doctor`

Runs installation and runtime checks, including CPU temperature and free disk space.

## Audio

`GET /api/audio/devices`

Returns ALSA hardware devices, logical devices, and mixer controls.

`GET /api/audio/mixer`

Returns the configured mixer state.

`GET /api/audio/volume`

Returns `{ "volume_percent": 40, "volume_range_db": 60 }`.

`POST /api/audio/volume`

Sets ALSA mixer volume. Accepts either key.

```json
{ "volume_percent": 40 }
```

`POST /api/audio/volume/up` / `POST /api/audio/volume/down`

Adjust volume by 5 percentage points.

If the configured mixer device doesn't expose ALSA controls (e.g. a stale
config pointing at a removed device), these endpoints probe detected
hardware cards and fall back to the first one with a working control.

`POST /api/diagnostics/test-sound`

Runs the configured test sound command.

## Services

`POST /api/service/spotify/start`

`POST /api/service/spotify/stop`

`POST /api/service/spotify/restart`

`POST /api/service/spotify/enable-now`

`POST /api/service/spotify/disable-now`

The UI intentionally controls only the Spotify engine service. Restarting the web service from its own request path is less predictable and is left to SSH/systemd.

## Logs

`GET /api/logs?target=spotify&lines=200`

Targets: `spotify`, `web`.

## Now Playing and History

`GET /api/nowplaying`

Returns the current track metadata from the librespot event pipeline, enriched with artist/album/cover when available. While playing, `position_estimate_ms` carries a server-side live position estimate so the UI can show progress without a Spotify Web API connection.

`GET /api/history`

Returns the last 50 played tracks (newest first) with `name`, `artists`, `album`, `cover_url`, `track_id`, and `played_at`.

`DELETE /api/history`

Clears the playback history.

## Sleep Timer

`GET /api/sleep-timer`

Returns `{ "active": false }` or the running timer with `action`, `ends_at`, and `remaining_seconds`.

`POST /api/sleep-timer`

Starts (or replaces) the timer. `action` is `pause` (Spotify Web API, falls back to stopping the engine) or `stop` (stops the engine service).

```json
{ "minutes": 30, "action": "pause" }
```

`DELETE /api/sleep-timer`

Cancels the timer.

## Spotify Web API proxy

Requires connecting a Spotify account from the dashboard (Client ID + PKCE OAuth; tokens are stored on the device).

`GET /api/spotify/status` — `{ "connected": true|false }`

`GET /api/spotify/player` — compact player state: `is_playing`, `shuffle`, `repeat`, `progress_ms`, `duration_ms`, `track`, `device`.

`GET /api/spotify/queue` — upcoming tracks.

`POST /api/spotify/play` / `POST /api/spotify/pause`

`POST /api/spotify/next` / `POST /api/spotify/previous`

`POST /api/spotify/shuffle` — body `{ "state": true }`

`POST /api/spotify/repeat` — body `{ "state": "off" | "context" | "track" }`

`GET /api/spotify/saved?id=<track_id>` — `{ "saved": true|false }` (Liked Songs)

`POST /api/spotify/save` — body `{ "id": "<track_id>", "saved": true|false }`

### `/api/player/*` — external client aliases

Same Spotify proxy as above, under simpler paths for programmatic clients
that expect a fixed shape (e.g. an AI assistant). Requires an active
Spotify Connect session — Spotify returns an error if nothing is playing
on this device.

`POST /api/player/play` / `POST /api/player/pause`

`POST /api/player/next` / `POST /api/player/previous`

`POST /api/player/volume` — body `{ "volume_percent": 50 }` (Spotify-side volume, separate from `/api/audio/volume`'s ALSA mixer)

`GET /api/player/state` — `{ "is_playing": true, "progress_ms": 45000, "track": { "name": ..., "artist": ..., "album": ..., "cover_url": ... } }`. `track` is `null` when nothing is loaded.

## Updates

`GET /api/update/check`

Fetches `origin/main` and returns `{ "available": true|false, "behind": N }`.

`POST /api/update`

Pulls the latest main, hot-reloads the installed package and static assets, and restarts both services.

## Profiles and Backups

`GET /api/profiles`

`POST /api/profiles/save`

`POST /api/profiles/load`

`DELETE /api/profiles/<name>`

`GET /api/backups`

`POST /api/backups/restore`

```json
{ "name": "config-20260507T180000000000Z.toml" }
```

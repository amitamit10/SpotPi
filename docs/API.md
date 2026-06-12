# API

The web UI uses a small JSON API. Default host and port:

```text
http://<raspberry-pi-ip>:8080
```

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

`POST /api/audio/volume`

Sets ALSA mixer volume.

```json
{ "percent": 40 }
```

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

Returns the current track metadata from the librespot event pipeline, enriched with artist/album/cover when available.

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

# Changelog

All notable changes to SpotPi are documented in this file.

## [0.3.0] - 2026-08-01

### Added
- **10-band graphic equalizer** (31 Hz – 16 kHz, ±12 dB per band) with 8 built-in presets (Flat, Bass Boost, Treble, Rock, Pop, Classical, Jazz, Vocal) and a live preset detector. Integrates with the ALSA equal plugin (`libasound2-plugin-equal`) via `amixer -D equal`; new `[equalizer]` config section and visual vertical-slider UI.
- **Calibration gain**: fixed gain offset (`[calibration]` section, ±12 dB, 0.5 dB steps) summed into the librespot normalisation pregain, with an EBU R128 reference-level setting and test-tone helper.
- New API: `GET`/`PUT /api/equalizer`, `POST /api/equalizer/reset`, `POST /api/equalizer/apply`.
- Spotify Web API playback controls on the dashboard: play/pause, previous/next, shuffle, repeat, queue, and player state proxy (server-side PKCE).
- Recently-played history panel (`/api/history`) with clear action.
- Sleep timer (`/api/sleep-timer`) — pause or stop after a countdown.
- Liked Songs heart on the now-playing card (`/api/spotify/saved` / `/api/spotify/save`).
- Progress bar that works without a Spotify account connection (server-side position estimate).
- PWA support: manifest, icons, and app-like install.
- Update-available badge and one-click Update (git pull + hot reload of the installed package) from the dashboard.
- Services panel in Advanced with per-service actions.
- Health endpoint (`/api/health`) and config export/import (`/api/settings/export`, `/api/settings/import`).
- OpenClaw-facing `/api/player/*` aliases and API-key authentication (`X-Api-Key`).
- Live CPU, RAM, load, and temperature stats plus new doctor checks.
- Setup wizard steps for Spotify skip/queue (Web API Client ID) with a copyable loopback redirect URI.

### Changed
- Version bumped to 0.3.0.
- Volume is synced bidirectionally between Spotify and the web UI.
- Dashboard redesigned (full-screen layout, hero, now-playing card, setup wizard).
- README expanded into a full-stack project showcase with Spotify Web API setup instructions.

### Fixed
- Spotify OAuth: moved PKCE to the server side, switched to a `127.0.0.1` loopback redirect with a paste-URL flow (crypto.subtle is unavailable over plain HTTP).
- Tolerate non-JSON success bodies from Spotify player-mutation endpoints (some return 200 with an opaque body instead of 204).
- Mixer fallback now prefers the ALSA card that exposes the configured control instead of the first responding card.
- `best_mixer_control` accepts the ALSA softvol `volume` capability.
- Now-playing card broken by systemd `PrivateTmp` isolation; metadata moved under `/var/lib/<service>`.
- Bound the Spotify open-graph metadata cache and capped the PIN re-prompt loop.
- Copy button uses `execCommand` so it works in an HTTP context.

[0.3.0]: https://github.com/amitamit10/SpotPi/compare/v1.0.2...v0.3.0

# SpotPi

<p align="center">
  <img alt="Python" src="https://img.shields.io/badge/Python-3.11+-3776AB?logo=python&logoColor=white">
  <img alt="JavaScript" src="https://img.shields.io/badge/JavaScript-ES2022-F7DF1E?logo=javascript&logoColor=black">
  <img alt="Raspberry Pi" src="https://img.shields.io/badge/Raspberry%20Pi-3B%2B-A22846?logo=raspberrypi&logoColor=white">
  <img alt="Docker" src="https://img.shields.io/badge/Docker-multi--stage-2496ED?logo=docker&logoColor=white">
  <img alt="Runtime" src="https://img.shields.io/badge/runtime-no%20Node%20%2F%20no%20DB-168443">
  <img alt="License" src="https://img.shields.io/badge/License-MIT-black">
</p>

> A full-stack embedded application that turns a Raspberry Pi into a self-hosted Spotify Connect speaker — with a responsive web dashboard for real-time monitoring and complete system configuration.

---

## Overview

SpotPi bridges the gap between embedded hardware and modern web interfaces. A custom Python REST API manages the [librespot](https://github.com/librespot-org/librespot) Spotify client process, while a vanilla JavaScript SPA (~1,200 LOC) exposes full system control through the browser. The device shows up in the Spotify app as a native Connect speaker — no cloud relay, no third-party Python dependencies.

```
Spotify App  ──────────────────────────────────────────────────────────┐
                                                                        │  Spotify Connect
                                                                   ┌────▼────────────┐
Browser  ──── HTTP/REST ──── Python API ──── systemd/ALSA ───────▶ │  librespot       │
             :8080           (stdlib only)                          │  (Rust binary)   │
                                    │                               └─────────────────┘
                                    └── TOML config  ← backup/profile management
```

---

## Tech Stack

### Backend — Python 3.11+ (stdlib only)

| Component | Implementation |
|-----------|---------------|
| HTTP Server | `ThreadingHTTPServer` with custom request routing |
| REST API | 30+ endpoints — JSON in/out, proper HTTP status codes |
| Config Engine | TOML schema with validation, atomic writes, auto-backup |
| Process Manager | `subprocess` + systemd integration (start/stop/restart/logs) |
| Audio Layer | ALSA device enumeration and mixer control via `subprocess` |
| Diagnostics | Structured health-check runner with per-check pass/fail reporting |
| Profile System | Named configuration snapshots — save, load, delete |
| Security | PIN authentication, command argument lists (no shell injection), systemd hardening |

### Frontend — Vanilla JavaScript SPA

| Component | Implementation |
|-----------|---------------|
| Architecture | Single-page app, two views: **Dashboard** and **Advanced Settings** |
| State | Polling-based real-time updates (status, now-playing, system stats) |
| UI | Responsive HTML5/CSS3, Geist font, no frameworks |
| Config Forms | Dynamic form generation from API schema (95 settings, 12 sections) |
| Volume | Live slider synced to ALSA hardware mixer |
| Logs | In-browser journal log viewer for both services |

### Infrastructure

| Component | Implementation |
|-----------|---------------|
| Containerization | Multi-stage Dockerfile — Rust build stage → Python runtime image |
| Service Management | Two systemd units: web API daemon + librespot engine |
| Installation | Single-command Bash installer (handles Rust/binary, user setup, systemd registration) |
| Event Pipeline | librespot lifecycle hooks → shell script → `/tmp/spotpi-nowplaying.json` → UI polling |

---

## Features

**Dashboard**
- Now-playing metadata (track, artist, album, cover art) via librespot event hooks
- Play/pause, skip, shuffle and repeat controls with a live progress bar (Spotify Web API)
- Up-next queue and recently-played history sheets
- Sleep timer: pause or stop playback after a chosen duration, with live countdown
- Power toggle to enable/disable Spotify Connect
- Audio output device selector (enumerates available ALSA PCM devices)
- System stats: IP address, live CPU usage, RAM, temperature, uptime
- Keyboard shortcuts (Space = play/pause, ←/→ = skip) and PWA install support

**Advanced Settings (95 configurable options across 12 sections)**
- Device name/type, timezone, language
- Web UI host, port, and PIN authentication
- Audio backend, output device, sample format, dither mode
- Volume normalization, startup level, control curve
- Playback bitrate (up to 320 kbps), gapless playback, local cache
- Network interface selection, offline handling
- Buffer presets, health-check watchdog, service supervision
- Log level, zeroconf backend, OAuth token management

**Operations**
- Doctor command — per-check diagnostics (ALSA, network, services, binary, CPU temp, disk space)
- Configuration backups with dated rotation (keeps last 20) plus one-click export/import
- Named profiles — save and restore complete setting sets
- Log viewer with selectable depth and one-click download
- Test-sound command for hardware speaker verification
- `/api/health` liveness endpoint for external monitoring
- One-click update (git pull + hot-reload, no restart required for static assets)

---

## Architecture

```
src/spotpi/
├── http_server.py     # Request router + 30+ REST endpoints
├── config.py          # TOML schema validation, atomic writes, backup engine
├── librespot.py       # CLI argument builder from config
├── system.py          # systemd + ALSA + journal wrappers
├── diagnostics.py     # Health-check runner + CPU/memory/disk sampling
├── history.py         # Recently-played track store
├── sleeptimer.py      # Sleep timer (pause/stop after a delay)
├── profiles.py        # Named config snapshots
├── cli.py             # CLI entry points (serve, doctor, profiles)
├── defaults.py        # Config schema and defaults
└── static/
    ├── index.html     # SPA shell
    ├── icon.svg       # Favicon / PWA icon
    ├── manifest.webmanifest
    └── assets/
        ├── app.js       # Application logic (~1000 LOC)
        ├── chrome.js    # UI event handling (~400 LOC)
        ├── features.js  # Player controls, history, sleep timer (~400 LOC)
        └── app.css      # Responsive styles
```

### Data Flow

1. User streams from Spotify → librespot receives audio over the network
2. librespot fires event hooks → `spotpi-event` script writes JSON to `/tmp/spotpi-nowplaying.json`
3. Frontend polls `/api/nowplaying` every 2 s → renders track info and status
4. Config changes → `PUT /api/settings` → validated TOML written atomically → librespot restarted with new args

---

## API Reference

<details>
<summary>Expand endpoint list</summary>

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/schema` | Configuration schema |
| `GET` | `/api/health` | Liveness: version + server uptime (no auth) |
| `GET` | `/api/settings` | Current config |
| `PUT` | `/api/settings` | Save config (triggers service restart) |
| `GET` | `/api/settings/export` | Download config as TOML |
| `POST` | `/api/settings/import` | Import config from TOML text |
| `GET` | `/api/status` | Playback status |
| `GET` | `/api/nowplaying` | Current track metadata |
| `GET` | `/api/history` | Recently played tracks (last 50) |
| `DELETE` | `/api/history` | Clear playback history |
| `GET/POST/DELETE` | `/api/sleep-timer` | Query, start, or cancel the sleep timer |
| `GET` | `/api/system` | CPU, RAM, load, temp, uptime |
| `GET` | `/api/doctor` | Diagnostics report |
| `GET` | `/api/audio/devices` | Available ALSA devices |
| `GET` | `/api/audio/mixer` | Mixer state |
| `POST` | `/api/audio/volume` | Set hardware volume |
| `GET` | `/api/logs` | Journal logs (`?target=spotify|web&lines=N`) |
| `POST` | `/api/service/{target}/{action}` | systemctl control |
| `POST` | `/api/diagnostics/test-sound` | Play test tone |
| `GET` | `/api/backups` | List backups |
| `POST` | `/api/backups/restore` | Restore backup |
| `GET` | `/api/profiles` | List profiles |
| `POST` | `/api/profiles/{save|load|delete}` | Manage profiles |
| `GET` | `/api/spotify/player` | Player state (progress, shuffle, repeat) |
| `POST` | `/api/spotify/{play\|pause\|next\|previous\|shuffle\|repeat}` | Playback control |
| `POST` | `/api/update` | Git pull + hot-reload |

</details>

---

## Getting Started

**Requirements**
- Raspberry Pi 3B+ running Raspberry Pi OS Lite
- USB DAC or compatible audio output
- Wi-Fi or Ethernet

**Install**

```bash
sudo apt-get update && sudo apt-get install -y git \
  && git clone https://github.com/amitamit10/spotpi.git \
  && cd spotpi \
  && sudo scripts/install.sh
```

Open **http://\<pi-ip\>:8080** — the device appears in Spotify as **SpotPi**.

> For alternative install modes (existing binary, apt, Cargo) see [Install Options](docs/OPERATIONS.md#install-options).

**Enable skip/queue controls (optional)**

To unlock skip, previous, queue and playback controls via the Spotify Web API:

1. Create a free app at [developer.spotify.com/dashboard](https://developer.spotify.com/dashboard) and tick **Web API**
2. Under **Redirect URIs** add exactly: `http://127.0.0.1:8080/`
   > Use the loopback IP — Spotify only allows HTTP for `127.0.0.1`/`localhost`, not LAN IPs like `192.168.x.x`
3. Copy the **Client ID** into SpotPi → Advanced → Web UI → *Spotify Client ID*
4. Click **Connect Spotify** on the dashboard and follow the on-screen steps (you'll paste a callback URL back into SpotPi)

**Verify installation**

```bash
sudo -u spotpi /opt/spotpi/venv/bin/spotpi-doctor
```

**Uninstall**

```bash
sudo scripts/uninstall.sh           # keeps config
sudo scripts/uninstall.sh --purge   # removes everything
```

---

## Local Development

```bash
# Clone and set up a virtual environment
git clone https://github.com/amitamit10/spotpi.git && cd spotpi
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

# Run the web server with a temp config (no librespot required)
PCS_CONFIG=/tmp/spotpi.toml python -m spotpi

# Run tests
python -m pytest tests/
```

The frontend is static — edit files under `src/spotpi/static/` and reload the browser.

**Docker (builds librespot from source)**

```bash
docker build -t spotpi .
```

---

## Documentation

| Doc | Contents |
|-----|----------|
| [Configuration](docs/CONFIGURATION.md) | All 95 settings, paths, security options |
| [Operations](docs/OPERATIONS.md) | Services, logs, install modes, updates |
| [API](docs/API.md) | Full endpoint reference with request/response schemas |
| [Architecture](docs/ARCHITECTURE.md) | Design decisions, module overview |
| [Troubleshooting](docs/TROUBLESHOOTING.md) | Common issues and fixes |

---

## Security

- All systemctl calls validate service names against an allowlist before execution
- `subprocess` always uses argument lists — no shell string interpolation
- Atomic config writes (temp file + `os.replace`) prevent partial-write corruption
- Optional PIN authentication for the web UI
- systemd hardening: `PrivateTmp`, `ProtectHome`, `ProtectSystem=full`, `NoNewPrivileges`
- Zero third-party Python dependencies — no supply-chain surface

---

> **Built with AI assistance:** Initial scaffolding via [OpenAI Codex](https://openai.com/blog/openai-codex); features, UI, and polish built collaboratively with [Claude Code](https://claude.ai/code) (Anthropic). Review before deploying.

Powered by [librespot](https://github.com/librespot-org/librespot) · MIT License

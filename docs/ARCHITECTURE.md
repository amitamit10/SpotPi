# Architecture

SpotPi is intentionally small.

## Components

- `spotpi.http_server`: local web UI and JSON API.
- `spotpi.config`: TOML load, validation, merge, and atomic save.
- `spotpi.librespot`: converts settings into a `librespot` command.
- `spotpi.system`: systemd, journal, ALSA, and test-sound wrappers.
- `spotpi.profiles`: save, load, list, and delete profile TOML files.
- `spotpi.diagnostics`: doctor checks and system summary.
- `spotpi.cli`: support commands for doctor, preview, and config bootstrap.
- `src/spotpi/static`: HTML, CSS, and JavaScript UI.

## Runtime

`spotpi.service` runs the web UI.

`spotpi-librespot.service` runs a Python wrapper that reads the same config and executes `librespot` with explicit arguments. Restarting this service is enough to apply playback-related settings.

## Stability Choices

- systemd owns process restart and boot startup.
- Config writes are atomic.
- Shell command execution uses argument lists, not string shell commands.
- Service names are validated before use.
- The backend catches command failures and returns structured API responses instead of crashing the UI.
- Runtime has no third-party Python dependencies.
- Config backups are created before overwriting an existing config.

## Development

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -e .
python -m unittest discover -s tests
python -m compileall src
```

Run locally with a temporary config:

```bash
PCS_CONFIG=/tmp/spotpi.toml python -m spotpi
```

Do not run `scripts/install.sh` on your development machine unless it is the target Raspberry Pi.

## Boundaries

The app does not implement Spotify playback itself. It only configures and supervises `librespot`.

The app does not manage Wi-Fi credentials. It assumes the Pi is already connected to the network.

The app does not replace `librespot`; it wraps it with settings, supervision, diagnostics, and a UI.

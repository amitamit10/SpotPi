# Architecture

Pi Connect Speaker is intentionally small.

## Components

- `pi_connect_speaker.http_server`: local web UI and JSON API.
- `pi_connect_speaker.config`: TOML load, validation, merge, and atomic save.
- `pi_connect_speaker.librespot`: converts settings into a `librespot` command.
- `pi_connect_speaker.system`: systemd, journal, ALSA, and test-sound wrappers.
- `pi_connect_speaker.profiles`: save, load, list, and delete profile TOML files.
- `pi_connect_speaker.diagnostics`: doctor checks and system summary.
- `pi_connect_speaker.cli`: support commands for doctor, preview, and config bootstrap.
- `src/pi_connect_speaker/static`: HTML, CSS, and JavaScript UI.

## Runtime

`pi-connect-speaker.service` runs the web UI.

`pi-connect-speaker-librespot.service` runs a Python wrapper that reads the same config and executes `librespot` with explicit arguments. Restarting this service is enough to apply playback-related settings.

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
PCS_CONFIG=/tmp/pi-connect-speaker.toml python -m pi_connect_speaker
```

Do not run `scripts/install.sh` on your development machine unless it is the target Raspberry Pi.

## Boundaries

The app does not implement Spotify playback itself. It only configures and supervises `librespot`.

The app does not manage Wi-Fi credentials. It assumes the Pi is already connected to the network.

The app does not replace `librespot`; it wraps it with settings, supervision, diagnostics, and a UI.

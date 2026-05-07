# Configuration

Active config:

```text
/etc/pi-connect-speaker/config.toml
```

Default template:

```text
config/default_config.toml
```

## Sections

`device`

Controls the Spotify Connect name, displayed device type, timezone, and UI language. The UI is English-only in V1.

`web`

Controls bind address, port, auth mode, PIN, and theme. Default auth mode is `none`.

`audio`

Controls playback backend, output device, ALSA mixer settings, sample format, and dithering.

For USB DACs, start with:

```toml
[audio]
backend = "alsa"
device_selection = "manual"
device = "hw:1,0"
mixer = "softvol"
```

Use the UI audio device list to select the correct `hw:X,Y` value.

`volume`

Controls startup volume, volume curve, software/hardware mixer behavior through `librespot`, and ReplayGain normalisation settings.

`quality`

Controls bitrate, cache paths, cache size, gapless playback, and autoplay.

`network`

Stores network recovery timing. The current V1 uses these settings as configuration state; systemd still handles process restart.

`stability`

Controls command timeout, health interval, watchdog preference, and whether an audio device must exist before start.

`service`

Controls service names, `librespot` path, autostart preference, log level, and zeroconf settings.

The default install grants the web UI limited sudo access for `pi-connect-speaker-librespot.service`. If you change `spotify_service_name`, update `/etc/sudoers.d/pi-connect-speaker` to match.

`diagnostics`

Controls log line count, refresh interval, test-sound behavior, and command preview visibility.

`backup`

Controls automatic config backups before save.

`profiles`

Controls where profile TOML files are stored.

`librespot`

Controls OAuth mode, cached username, access token, and extra arguments.

## File Paths

| Path | Purpose |
| --- | --- |
| `/etc/pi-connect-speaker/config.toml` | Active configuration |
| `/etc/pi-connect-speaker/profiles` | Saved profiles |
| `/etc/pi-connect-speaker/backups` | Automatic config backups |
| `/var/cache/pi-connect-speaker` | Librespot audio/system cache |

## Security

The web UI defaults to `auth_mode = "none"` for trusted home networks. Do not expose port `8080` to the internet. For stricter use, set `web.host = "127.0.0.1"` or `web.auth_mode = "pin"`.

## Applying Changes

Settings are saved immediately to TOML. Audio and Spotify Connect settings take effect after restarting `pi-connect-speaker-librespot.service`.

Use the UI `Save & Restart` button or:

```bash
sudo systemctl restart pi-connect-speaker-librespot.service
```

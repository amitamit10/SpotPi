# Operations

## Install Options

`scripts/install.sh` uses an existing `librespot` binary when available. Otherwise it tries the OS package, then falls back to building with Cargo.

```bash
sudo LIBRESPOT_INSTALL_MODE=existing scripts/install.sh
sudo LIBRESPOT_INSTALL_MODE=apt     scripts/install.sh
sudo LIBRESPOT_INSTALL_MODE=auto    scripts/install.sh
```

## Services

```bash
sudo systemctl status pi-connect-speaker.service
sudo systemctl status pi-connect-speaker-librespot.service
```

Start:

```bash
sudo systemctl start pi-connect-speaker.service
sudo systemctl start pi-connect-speaker-librespot.service
```

Restart Spotify Connect only:

```bash
sudo systemctl restart pi-connect-speaker-librespot.service
```

## Doctor

```bash
sudo -u pi-connect-speaker /opt/pi-connect-speaker/venv/bin/pi-connect-speaker-doctor
```

Or from a source checkout:

```bash
scripts/doctor.sh
```

## Logs

```bash
journalctl -u pi-connect-speaker.service -n 200 --no-pager
journalctl -u pi-connect-speaker-librespot.service -n 200 --no-pager
```

## Config Backups

Backups live in:

```text
/etc/pi-connect-speaker/backups
```

Restore from the UI or copy a backup over:

```bash
sudo cp /etc/pi-connect-speaker/backups/<backup>.toml /etc/pi-connect-speaker/config.toml
sudo chown pi-connect-speaker:pi-connect-speaker /etc/pi-connect-speaker/config.toml
sudo systemctl restart pi-connect-speaker-librespot.service
```

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
sudo systemctl status spotpi.service
sudo systemctl status spotpi-librespot.service
```

Start:

```bash
sudo systemctl start spotpi.service
sudo systemctl start spotpi-librespot.service
```

Restart Spotify Connect only:

```bash
sudo systemctl restart spotpi-librespot.service
```

## Doctor

```bash
sudo -u spotpi /opt/spotpi/venv/bin/spotpi-doctor
```

Or from a source checkout:

```bash
scripts/doctor.sh
```

## Logs

```bash
journalctl -u spotpi.service -n 200 --no-pager
journalctl -u spotpi-librespot.service -n 200 --no-pager
```

## Config Backups

Backups live in:

```text
/etc/spotpi/backups
```

Restore from the UI or copy a backup over:

```bash
sudo cp /etc/spotpi/backups/<backup>.toml /etc/spotpi/config.toml
sudo chown spotpi:spotpi /etc/spotpi/config.toml
sudo systemctl restart spotpi-librespot.service
```

# Pi Connect Speaker

Turn a Raspberry Pi into a Spotify Connect speaker with a web UI for settings.

## Requirements

- Raspberry Pi 3B+ running Raspberry Pi OS Lite
- USB DAC connected to a speaker/receiver
- Wi-Fi or Ethernet

## Install

```bash
git clone https://github.com/<owner>/pi-connect-speaker.git
cd pi-connect-speaker
sudo START_NOW=1 scripts/install.sh
```

Then open **http://\<pi-ip\>:8080** in your browser.

The device will appear in Spotify as **PiConnect Speaker**.

## Verify

```bash
sudo -u pi-connect-speaker /opt/pi-connect-speaker/venv/bin/pi-connect-speaker-doctor
```

## Uninstall

```bash
sudo scripts/uninstall.sh           # keeps config
sudo scripts/uninstall.sh --purge   # removes everything
```

## Docs

[Configuration](docs/CONFIGURATION.md) · [Operations](docs/OPERATIONS.md) · [API](docs/API.md) · [Troubleshooting](docs/TROUBLESHOOTING.md)

---

Powered by [librespot](https://github.com/librespot-org/librespot) · MIT License

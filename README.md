# Pi Connect Speaker

<p align="center">
  <img alt="Python" src="https://img.shields.io/badge/Python-3.11+-3776AB?logo=python&logoColor=white">
  <img alt="Raspberry Pi" src="https://img.shields.io/badge/Raspberry%20Pi-3B+-A22846?logo=raspberrypi&logoColor=white">
  <img alt="Runtime" src="https://img.shields.io/badge/Runtime-no%20Node%20%2F%20no%20DB-168443">
  <img alt="License" src="https://img.shields.io/badge/License-MIT-black">
</p>

Turn a Raspberry Pi into a Spotify Connect speaker with a web UI for settings.

## Requirements

- Raspberry Pi 3B+ running Raspberry Pi OS Lite
- USB DAC connected to a speaker/receiver
- Wi-Fi or Ethernet

## Install

```bash
git clone https://github.com/<owner>/pi-connect-speaker.git && cd pi-connect-speaker && sudo scripts/install.sh
```

Then open **http://\<pi-ip\>:8080** in your browser.

The device will appear in Spotify as **PiConnect Speaker**.

> For custom install modes (existing binary, apt, Cargo) see [Install Options](docs/OPERATIONS.md#install-options).

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

- [Configuration & Paths & Security](docs/CONFIGURATION.md)
- [Operations & Services & Logs](docs/OPERATIONS.md)
- [API](docs/API.md)
- [Architecture & Development](docs/ARCHITECTURE.md)
- [Troubleshooting](docs/TROUBLESHOOTING.md)

---

> **Note:** This project was built with the assistance of [Claude Code](https://claude.ai/code) (Anthropic's AI coding assistant). Review the code before deploying to production.

Powered by [librespot](https://github.com/librespot-org/librespot) · MIT License

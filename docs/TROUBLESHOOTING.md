# Troubleshooting

## Device Does Not Appear in Spotify

Run the built-in checks first:

```bash
sudo -u spotpi /opt/spotpi/venv/bin/spotpi-doctor
```

Check services:

```bash
systemctl status spotpi.service
systemctl status spotpi-librespot.service
```

Check discovery/network basics:

```bash
systemctl status avahi-daemon.service
hostname -I
```

## No Sound

List ALSA devices:

```bash
aplay -l
aplay -L
```

Pick the USB DAC in the web UI under `Audio Devices`, then save and restart.

Check logs:

```bash
journalctl -u spotpi-librespot.service -n 200 --no-pager
```

## Crackling or Dropouts

Use conservative settings first:

```toml
[audio]
backend = "alsa"
format = "S16"
dither = "tpdf"

[quality]
bitrate_kbps = 320

[stability]
buffer_preset = "stable"
```

Use a stable power supply and avoid overloaded USB hubs.

## Web UI Not Reachable

Check the web service:

```bash
systemctl status spotpi.service
```

Check the configured port:

```bash
grep -n "port" /etc/spotpi/config.toml
```

Default URL:

```text
http://<raspberry-pi-ip>:8080
```

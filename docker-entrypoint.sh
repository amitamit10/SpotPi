#!/bin/bash
set -e

# Start librespot in the background
# We use the built-in spotpi-librespot command
echo "Starting librespot..."
spotpi-librespot &

# Start the web UI
echo "Starting SpotPi Web UI..."
exec spotpi

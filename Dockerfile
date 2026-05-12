# Use an official Python runtime as a parent image
FROM python:3.11-slim

# Install system dependencies
RUN apt-get update && apt-get install -y \
    alsa-utils \
    libasound2-dev \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install librespot
# This downloads the latest librespot binary for linux-amd64.
# For Raspberry Pi (ARM), the user would ideally use a different binary,
# but for the general release we'll provide a standard one.
RUN curl -L https://github.com/librespot-org/librespot/releases/latest/download/librespot-linux-amd64.tar.gz | tar -xz -C /usr/local/bin

# Set up application directory
WORKDIR /app

# Copy the current directory contents into the container at /app
COPY . .

# Install the spotpi package
RUN pip install .

# Create necessary directories
RUN mkdir -p /etc/spotpi /var/cache/spotpi/audio /etc/spotpi/backups /etc/spotpi/profiles

# Environment variables
ENV PCS_CONFIG=/etc/spotpi/config.toml
ENV SPOTPI_DOCKER=1
ENV PYTHONUNBUFFERED=1

# Make entrypoint executable
RUN chmod +x docker-entrypoint.sh

# Expose the web UI port
EXPOSE 8080

# The command to run the application
ENTRYPOINT ["./docker-entrypoint.sh"]

# Docker Usage Guide

## Quick Start with Setup Scripts

We provide convenient setup scripts for both Linux/macOS and Windows users.

### Linux/macOS Users

```bash
# Make script executable
chmod +x docker-setup.sh

# Create necessary directories
./docker-setup.sh setup

# Start the container
./docker-setup.sh start

# View container logs
./docker-setup.sh logs

# Check container status
./docker-setup.sh status
```

### Windows Users

```powershell
# Create necessary directories
.\docker-setup.ps1 setup

# Start the container
.\docker-setup.ps1 start

# View container logs
.\docker-setup.ps1 logs

# Check container status
.\docker-setup.ps1 status
```

## Using Pre-built Docker Image

You can use the pre-built Docker image from GitHub Container Registry:

```bash
# Create a data directory to store persistent data
mkdir -p ./data

# Run using Docker
docker run -d \
  --name twitch-drops-miner \
  -p 8080:8080 \
  -v ./data/logs:/app/logs \
  -v ./data/cache:/app/cache \
  -v ./data/settings.json:/app/settings.json \  -v ./data/cookies.jar:/app/cookies.jar \
  ghcr.io/kaysharp42/twitchdropsminer-web:latest
```

## Using Docker Compose

1. Create a `.env` file (optional) to customize your environment:

```
DATA_DIR=./data
WEB_PORT=8080
TIMEZONE=UTC
```

2. Run with Docker Compose:

```bash
# Pull and start the container
docker-compose up -d

# Check logs
docker-compose logs -f
```

## Building the Image Locally

If you prefer to build the image yourself:

```bash
# Build the image
docker build -t twitchdropsminer-web .

# Run the container
docker run -d \
  --name twitch-drops-miner \
  -p 8080:8080 \
  -v ./data/logs:/app/logs \
  -v ./data/cache:/app/cache \
  -v ./data/settings.json:/app/settings.json \
  -v ./data/cookies.jar:/app/cookies.jar \
  twitch-drops-miner
```

## Initial Setup

1. Access the web interface at http://localhost:8080
2. Navigate to the Login tab to authenticate with Twitch
3. Configure your preferred settings
4. The miner will automatically start tracking available drops

## Notes

- The Docker image runs the application with the web interface enabled
- Data persistence is handled through volume mounts
- Use the web interface to monitor and control the miner

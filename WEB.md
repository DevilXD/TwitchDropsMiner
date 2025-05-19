# TwitchDropsMinerWeb

Enhanced fork of [TwitchDropsMiner](https://github.com/DevilXD/TwitchDropsMiner) with improved web interface capabilities and Docker support.

## Web Interface Features

The web interface allows you to:

- Monitor and control the miner from any browser
- View active drop campaigns and progress
- Check available channels and their status
- View claimed and pending drops in your inventory
- Manage login and authentication
- Configure application settings

## Docker Deployment

This fork adds comprehensive Docker support for easy deployment in containers. The app automatically runs in web-only mode when deployed in Docker:

1. **Quick Start:**
   ```powershell
   # Create necessary directories
   .\docker-setup.ps1 setup

   # Start the container
   .\docker-setup.ps1 start
   ```

2. **Access the Interface:**
   Open your browser and go to: `http://localhost:8080`

## GitHub Container Registry

Pre-built images are available on GitHub Container Registry:
```bash
docker pull ghcr.io/kaysharp42/twitchdropsminer-web:latest
```

## Configuration

All settings can be configured via the web interface. The application stores:
- Logs in `./data/logs/`
- Cache in `./data/cache/`
- Settings in `./data/settings.json`
- Authentication in `./data/cookies.jar`

See the [Docker Usage Guide](DOCKER.md) for detailed instructions.

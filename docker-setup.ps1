# PowerShell script to help set up and run TwitchDropsMinerWeb in Docker
# Usage: .\docker-setup.ps1 [command]
# Commands: setup, start, stop, logs, update

param(
    [Parameter(Position=0)]
    [string]$Command = "help"
)

# Default settings
$DATA_DIR = "./data"
$WEB_PORT = "8080"

# Create directories if they don't exist
function Setup-Directories {
    if (-not (Test-Path "$DATA_DIR")) {
        New-Item -ItemType Directory -Path "$DATA_DIR" | Out-Null
    }
    if (-not (Test-Path "$DATA_DIR/logs")) {
        New-Item -ItemType Directory -Path "$DATA_DIR/logs" | Out-Null
    }
    if (-not (Test-Path "$DATA_DIR/cache")) {
        New-Item -ItemType Directory -Path "$DATA_DIR/cache" | Out-Null
    }
    if (-not (Test-Path "$DATA_DIR/settings.json")) {
        New-Item -ItemType File -Path "$DATA_DIR/settings.json" | Out-Null
    }
    if (-not (Test-Path "$DATA_DIR/cookies.jar")) {
        New-Item -ItemType File -Path "$DATA_DIR/cookies.jar" | Out-Null
    }
    Write-Host "Created data directories in $DATA_DIR"
}

# Show usage information
function Show-Usage {
    Write-Host "Usage: .\docker-setup.ps1 [command]"
    Write-Host "Commands:"
    Write-Host "  setup   - Create necessary directories"
    Write-Host "  start   - Start the TwitchDropsMiner container"
    Write-Host "  stop    - Stop the container"
    Write-Host "  logs    - Show container logs"
    Write-Host "  update  - Update to the latest image version"
    Write-Host "  status  - Check if container is running"
}

# Check if Docker is installed
if (-not (Get-Command "docker" -ErrorAction SilentlyContinue)) {
    Write-Host "Docker is not installed. Please install Docker Desktop for Windows first." -ForegroundColor Red
    exit 1
}

# Process commands
switch ($Command.ToLower()) {
    "setup" {
        Setup-Directories
        Write-Host "Setup complete. You can now start the container with: .\docker-setup.ps1 start"
    }    "start" {
        Setup-Directories
        Write-Host "Starting TwitchDropsMinerWeb container..." 
        docker-compose up -d
        Write-Host "Container started! The web interface is available at http://localhost:$WEB_PORT"
    }
    "stop" {
        Write-Host "Stopping TwitchDropsMinerWeb container..."
        docker-compose down
        Write-Host "Container stopped."
    }
    "logs" {
        docker-compose logs -f
    }
    "update" {
        Write-Host "Updating TwitchDropsMinerWeb to the latest version..."
        docker-compose pull
        docker-compose down
        docker-compose up -d
        Write-Host "Update complete! Container restarted with the latest version."
    }
    "status" {
        $containerStatus = docker-compose ps
        if ($containerStatus -match "twitch-drops-miner") {
            Write-Host "TwitchDropsMinerWeb is running." -ForegroundColor Green
            Write-Host "Web interface is available at http://localhost:$WEB_PORT"
        } else {
            Write-Host "TwitchDropsMiner is not running." -ForegroundColor Yellow
        }
    }
    default {
        Show-Usage
    }
}

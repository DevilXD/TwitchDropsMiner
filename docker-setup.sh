#!/bin/bash

# Script to help set up and run TwitchDropsMinerWeb in Docker
# Usage: ./docker-setup.sh [command]
# Commands: setup, start, stop, logs, update

# Default settings
DATA_DIR="./data"
WEB_PORT="8080"

# Create directories if they don't exist
setup_directories() {
    mkdir -p "$DATA_DIR"
    
    # Copy .env.example to .env if .env doesn't exist
    if [ ! -f ".env" ]; then
        if [ -f ".env.example" ]; then
            echo "Creating .env from .env.example..."
            cp ".env.example" ".env"
            echo ".env file created successfully."
        else
            echo "Warning: .env.example not found. Skipping .env creation."
        fi
    else
        echo ".env file already exists, skipping copy."
    fi
}

# Show usage information
show_usage() {
    echo "Usage: $0 [command]"
    echo "Commands:"
    echo "  setup   - Create necessary directories"
    echo "  start   - Start the TwitchDropsMiner container"
    echo "  stop    - Stop the container"
    echo "  logs    - Show container logs"
    echo "  update  - Update to the latest image version"
    echo "  status  - Check if container is running"
}

# Check if Docker is installed
if ! command -v docker &> /dev/null; then
    echo "Docker is not installed. Please install Docker first."
    exit 1
fi

# Process commands
case "$1" in
    setup)
        setup_directories
        echo "Setup complete. You can now start the container with: $0 start"
        ;;
    start)
        setup_directories
        echo "Starting TwitchDropsMinerWeb container..."
        docker-compose up -d
        echo "Container started! The web interface is available at http://localhost:$WEB_PORT"
        ;;
    stop)
        echo "Stopping TwitchDropsMinerWeb container..."
        docker-compose down
        echo "Container stopped."
        ;;
    logs)
        docker-compose logs -f
        ;;
    update)
        echo "Updating TwitchDropsMinerWeb to the latest version..."
        docker-compose pull
        docker-compose down
        docker-compose up -d
        echo "Update complete! Container restarted with the latest version."
        ;;
    status)
        if docker-compose ps | grep -q "twitch-drops-miner"; then
            echo "TwitchDropsMinerWeb is running."
            echo "Web interface is available at http://localhost:$WEB_PORT"
        else
            echo "TwitchDropsMiner is not running."
        fi
        ;;
    *)
        show_usage
        ;;
esac

#!/bin/bash

# Set Docker container indicator
export DOCKER_CONTAINER=true

# Create data directory if it doesn't exist
mkdir -p /data

# Copy .env.example to .env if .env doesn't exist
if [ ! -f /app/.env ]; then
    if [ -f /app/.env.example ]; then
        echo "Creating .env from .env.example"
        cp /app/.env.example /app/.env
        echo ".env file created successfully"
    else
        echo "Warning: .env.example not found. Skipping .env creation."
    fi
else
    echo ".env file already exists, skipping copy."
fi

# Check if settings.json exists in /data, if not create with default values
if [ ! -f /data/settings.json ]; then
    echo "Creating default settings.json in /data directory"
    cat > /data/settings.json << 'EOL'
{
    "autostart_tray": false,
    "connection_quality": 1,
    "exclude": {
        "__type": "set",
        "data": []
    },
    "gui_enabled": false,
    "language": "",
    "priority": [],
    "priority_mode": {
        "__type": "PriorityMode",
        "data": 1
    },
    "proxy": {
        "__type": "URL",
        "data": ""
    },
    "tray_notifications": true
}
EOL
fi

# Create empty cookies.jar if it doesn't exist
if [ ! -f /data/cookies.jar ]; then
    echo "Creating empty cookies.jar in /data directory"
    touch /data/cookies.jar
fi

# Create empty credentials.json if it doesn't exist (for authentication)
if [ ! -f /data/credentials.json ]; then
    echo "Creating empty credentials.json in /data directory"
    echo '{"users": [], "setup_complete": false}' > /data/credentials.json
fi

# Create empty blacklist.json if it doesn't exist (for authentication)
if [ ! -f /data/blacklist.json ]; then
    echo "Creating empty blacklist.json in /data directory"
    echo '{"blacklisted_tokens": {}, "last_cleanup": 0}' > /data/blacklist.json
fi

# Remove existing files if they exist to avoid symbolic link errors
rm -f /app/settings.json /app/cookies.jar /app/credentials.json /app/blacklist.json

# Ensure proper permissions on the data files
chmod 755 /data/settings.json /data/cookies.jar /data/credentials.json /data/blacklist.json

# Create symbolic links
ln -sf /data/settings.json /app/settings.json
ln -sf /data/cookies.jar /app/cookies.jar
ln -sf /data/credentials.json /app/credentials.json
ln -sf /data/blacklist.json /app/blacklist.json

# Debug permissions
echo "Current user: $(whoami)"
echo "File permissions:"
ls -la /data/
ls -la /app/settings.json /app/cookies.jar /app/credentials.json /app/blacklist.json

echo "Verifying Python imports..."
python -c "import sys; print(sys.path)"
python -c "import yarl; print(f\"yarl version: {yarl.__version__}\")"
python -c "import aiohttp; print(f\"aiohttp version: {aiohttp.__version__}\")"

echo "Checking JWT secret..."
# Check if JWT_SECRET is empty in .env file
if grep -q "JWT_SECRET=$" /app/.env 2>/dev/null || ! grep -q "JWT_SECRET=" /app/.env 2>/dev/null; then
    echo "Generating new JWT secret..."
    python /app/generate_jwt_secret.py
fi

echo "Starting TwitchDropsMiner..."
exec python docker_main.py
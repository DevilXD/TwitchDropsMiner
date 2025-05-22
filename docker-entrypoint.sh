#!/bin/bash

# Create data directory if it doesn't exist
mkdir -p /data

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

# Remove existing files if they exist to avoid symbolic link errors
rm -f /app/settings.json /app/cookies.jar

# Ensure proper permissions on the data files
chmod 666 /data/settings.json /data/cookies.jar

# Create symbolic links
ln -sf /data/settings.json /app/settings.json
ln -sf /data/cookies.jar /app/cookies.jar

# Debug permissions
echo "Current user: $(whoami)"
echo "File permissions:"
ls -la /data/
ls -la /app/settings.json /app/cookies.jar

echo "Verifying Python imports..."
python -c "import sys; print(sys.path)"
python -c "import yarl; print(f\"yarl version: {yarl.__version__}\")"
python -c "import aiohttp; print(f\"aiohttp version: {aiohttp.__version__}\")"

echo "Starting TwitchDropsMiner..."
exec python docker_main.py
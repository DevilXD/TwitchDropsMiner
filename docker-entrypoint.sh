#!/bin/bash

echo "Verifying Python imports..."
python -c "import sys; print(sys.path)"
python -c "import yarl; print(f\"yarl version: {yarl.__version__}\")"
python -c "import aiohttp; print(f\"aiohttp version: {aiohttp.__version__}\")"

echo "Setting up data directory..."
mkdir -p /data

# Ensure correct ownership of the data directory
if [ ! -w "/data" ]; then
    echo "Warning: /data directory is not writable by current user. The application may not work correctly."
fi

echo "Starting TwitchDropsMiner..."
exec python docker_main.py
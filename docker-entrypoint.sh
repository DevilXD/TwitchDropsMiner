#!/bin/bash

echo "Verifying Python imports..."
python -c "import sys; print(sys.path)"
python -c "import yarl; print(f\"yarl version: {yarl.__version__}\")"
python -c "import aiohttp; print(f\"aiohttp version: {aiohttp.__version__}\")"

echo "Starting TwitchDropsMiner..."
exec python docker_main.py
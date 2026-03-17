#!/usr/bin/env bash

dirpath=$(dirname "$(readlink -f "$0")")

# Check if uv is installed
if ! command -v uv &> /dev/null; then
    echo
    echo "No uv executable found in PATH!"
    echo "Please install uv first: https://docs.astral.sh/uv/getting-started/installation/"
    echo
    read -p "Press any key to continue..."
    exit 1
fi

# Synchronize the environment
echo
echo "Synchronizing the environment using uv..."
uv sync
if [ $? -ne 0 ]; then
    echo
    echo "Failed to synchronize the environment."
    echo
    read -p "Press any key to continue..."
    exit 1
fi

echo
echo "Environment setup completed successfully."
echo
read -p "Press any key to continue..."

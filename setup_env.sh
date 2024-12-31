#!/usr/bin/env bash

dirpath=$(dirname "$(readlink -f "$0")")

# Check if git is installed
if ! command -v git &> /dev/null; then
    echo
    echo "No git executable found in PATH!"
    echo
    read -p "Press any key to continue..."
    exit 1
fi

# Check if the virtual environment exists
if [ ! -d "$dirpath/env" ]; then
    echo
    echo "Creating the env folder..."
    python3 -m venv "$dirpath/env"
    if [ $? -ne 0 ]; then
        echo
        echo "No python executable found in PATH or failed to create virtual environment!"
        echo
        read -p "Press any key to continue..."
        exit 1
    fi
fi

# Activate the virtual environment and install requirements
echo
echo "Installing requirements.txt..."
"$dirpath/env/bin/python" -m pip install -U pip
"$dirpath/env/bin/pip" install wheel
"$dirpath/env/bin/pip" install -r "$dirpath/requirements.txt"
if [ $? -ne 0 ]; then
    echo
    echo "Failed to install requirements."
    echo
    read -p "Press any key to continue..."
    exit 1
fi

echo
echo "Environment setup completed successfully."
echo
read -p "Press any key to continue..."

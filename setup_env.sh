#!/usr/bin/env bash

dirpath=$(dirname "$(readlink -f "$0")")

# Check if git is installed
if ! command -v git &> /dev/null; then
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
if [ $? -ne 0 ]; then
    echo "Failed to upgrade pip."
    exit 1
fi

"$dirpath/env/bin/pip" install wheel
if [ $? -ne 0 ]; then
    echo "Failed to install wheel."
    exit 1
fi

"$dirpath/env/bin/pip" install -r "$dirpath/requirements.txt"
if [ $? -ne 0 ]; then
    echo "Failed to install requirements."
    exit 1
fi

echo
echo "All done!"
echo
read -p "Press any key to continue..."
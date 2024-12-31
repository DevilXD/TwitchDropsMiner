#!/usr/bin/env bash

dirpath=$(dirname "$(readlink -f "$0")")

# Check if the virtual environment exists
if [ ! -d "$dirpath/env" ]; then
    echo
    echo "No virtual environment found! Run setup_env.sh to set it up first."
    echo
    read -p "Press any key to continue..."
    exit 1
fi

# Check if pyinstaller is installed in the virtual environment
if [ ! -f "$dirpath/env/bin/pyinstaller" ]; then
    echo
    echo "Installing pyinstaller..."
    "$dirpath/env/bin/pip" install pyinstaller
    if [ $? -ne 0 ]; then
        echo "Failed to install pyinstaller."
        exit 1
    fi
fi

# Run pyinstaller with the specified build spec file
echo
echo "Running pyinstaller..."
"$dirpath/env/bin/pyinstaller" "$dirpath/build.spec"
if [ $? -ne 0 ]; then
    echo "PyInstaller build failed."
    exit 1
fi

echo
echo "Build completed successfully."
read -p "Press any key to continue..."

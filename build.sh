#!/usr/bin/env bash

dirpath=$(dirname "$(readlink -f "$0")")

# Check if the virtual environment exists
if [ ! -d "$dirpath/env" ]; then
    echo
    echo "No virtual environment found! Run setup_env.sh to set it up first."
    echo
    [ "$1" != "--nopause" ] && read -p "Press any key to continue..."
    exit 1
fi

# Check if PyInstaller is installed in the virtual environment
if [ ! -f "$dirpath/env/bin/pyinstaller" ]; then
    echo
    echo "Installing PyInstaller..."
    "$dirpath/env/bin/pip" install pyinstaller
    if [ $? -ne 0 ]; then
        echo
        echo "Failed to install PyInstaller."
        echo
        [ "$1" != "--nopause" ] && read -p "Press any key to continue..."
        exit 1
    fi
fi

# Run PyInstaller with the specified build spec file
echo
echo "Building..."
"$dirpath/env/bin/pyinstaller" "$dirpath/build.spec"
if [ $? -ne 0 ]; then
    echo
    echo "PyInstaller build failed."
    echo
    [ "$1" != "--nopause" ] && read -p "Press any key to continue..."
    exit 1
fi

echo
echo "Build completed successfully."
echo
[ "$1" != "--nopause" ] && read -p "Press any key to continue..."

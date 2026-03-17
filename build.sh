#!/usr/bin/env bash

dirpath=$(dirname "$(readlink -f "$0")")

# Check if uv is installed
if ! command -v uv &> /dev/null; then
    echo
    echo "No uv executable found in PATH!"
    echo "Please install uv first: https://docs.astral.sh/uv/getting-started/installation/"
    echo
    [ "$1" != "--nopause" ] && read -p "Press any key to continue..."
    exit 1
fi

# Run PyInstaller with the specified build spec file
echo
echo "Building..."
uv run pyinstaller "$dirpath/build.spec"
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

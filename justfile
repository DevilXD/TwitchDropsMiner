set shell := ["powershell", "-NoProfile", "-Command"]

is_windows := if os() == "windows" { "true" } else { "false" }
is_linux := if os() == "linux" { "true" } else { "false" }
is_macos := if os() == "macos" { "true" } else { "false" }

# Python executable name based on OS
py := if os() == "windows" { "python" } else { "python3" }
pyw := if os() == "windows" { "pythonw" } else { "python3" }

# Synchronize the environment using uv
setup:
    uv sync

# Run the application in development mode
# Usage: just run           (No console)
# Usage: just run console=y (With console)
run console="n":
    @if ("{{console}}" -eq "y") { uv run {{py}} main.py } else { uv run {{pyw}} main.py }

# Build the application using PyInstaller
build:
    uv run pyinstaller build.spec

# Package the application (Cross-platform ZIP)
pack: build
    uv run {{py}} scripts/pack_app.py

# Clean up build artifacts (Cross-platform)
clean:
    uv run {{py}} scripts/clean_app.py

# Build Linux AppImage (Requires appimage-builder)
appimage:
    @if ("{{os()}}" -ne "linux") { Write-Error "AppImage build only supported on Linux"; exit 1 }
    uv run appimage-builder --recipe appimage/AppImageBuilder.yml

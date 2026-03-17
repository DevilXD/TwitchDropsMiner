set shell := if os() == "windows" { ["powershell", "-NoProfile", "-Command"] } else { ["sh", "-c"] }

is_windows := os() == "windows"
is_linux := os() == "linux"
is_macos := os() == "macos"

# Python executable name based on OS
py := if is_windows { "python" } else { "python3" }
pyw := if is_windows { "pythonw" } else { "python3" }

# Synchronize the environment using uv
setup:
    uv sync

# Run the application in development mode
# Usage: just run           (No console)
# Usage: just run console=y (With console)
run console="n":
    @{{ if console == "y" { "uv run " + py + " main.py" } else { "uv run " + pyw + " main.py" } }}

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
    @if [ "{{os()}}" != "linux" ]; then echo "AppImage build only supported on Linux"; exit 1; fi
    uv run appimage-builder --recipe appimage/AppImageBuilder.yml

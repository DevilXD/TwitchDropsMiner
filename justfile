set shell := ["powershell", "-NoProfile", "-Command"]

# Synchronize the environment using uv
setup:
    uv sync

# Run the application in development mode
run console="n":
    @if "{{console}}" == "y" { \
        uv run python main.py; \
    } else { \
        uv run pythonw main.py; \
    }

# Build the application using PyInstaller
build:
    uv run pyinstaller build.spec

# Package the application (Windows)
pack: build
    @if (!(Test-Path "7z.exe")) { \
        Write-Error "No 7z.exe detected, skipping packaging!"; \
        exit 1; \
    }
    if (!(Test-Path "Twitch Drops Miner")) { New-Item -ItemType Directory "Twitch Drops Miner" }
    Copy-Item "dist\*.exe" "Twitch Drops Miner" -Force
    Copy-Item "manual.txt" "Twitch Drops Miner" -Force
    $action = if (Test-Path "Twitch Drops Miner.zip") { "u" } else { "a" }
    & .\7z.exe $action "Twitch Drops Miner.zip" "Twitch Drops Miner/" -r
    & .\7z.exe t "Twitch Drops Miner.zip" * -r
    Remove-Item -Recurse -Force "Twitch Drops Miner"

# Clean up build artifacts
clean:
    if (Test-Path "dist") { Remove-Item -Recurse -Force "dist" }
    if (Test-Path "build") { Remove-Item -Recurse -Force "build" }
    if (Test-Path ".venv") { Remove-Item -Recurse -Force ".venv" }

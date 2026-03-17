@echo off

REM Get the directory path of the script
set "dirpath=%~dp0"
if "%dirpath:~-1%" == "\" set "dirpath=%dirpath:~0,-1%"

REM Check if uv is installed
uv --version > nul 2>&1
if %errorlevel% NEQ 0 (
    echo:
    echo No uv executable found in PATH!
    echo Please install uv first: https://docs.astral.sh/uv/getting-started/installation/
    echo:
    pause
    exit /b 1
)

REM Run PyInstaller with the specified build spec file
echo Building...
uv run pyinstaller "%dirpath%\build.spec"
if errorlevel 1 (
    echo:
    echo PyInstaller build failed.
    echo:
    if not "%~1"=="--nopause" pause
    exit /b 1
)

echo:
echo Build completed successfully.
echo:
if not "%~1"=="--nopause" pause

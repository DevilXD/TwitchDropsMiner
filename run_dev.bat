@echo off
cls
set dirpath=%~dp0
if "%dirpath:~-1%" == "\" set dirpath=%dirpath:~0,-1%

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

set /p "choice=Start with a console? (y/n) "
if "%choice%"=="y" (
    start "TwitchDropsMiner" uv run python "%dirpath%\main.py"
) else (
    start "TwitchDropsMiner" uv run pythonw "%dirpath%\main.py"
)

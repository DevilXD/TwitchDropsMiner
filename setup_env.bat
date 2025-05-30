@echo off

REM Get the directory path of the script
set "dirpath=%~dp0"
if "%dirpath:~-1%" == "\" set "dirpath=%dirpath:~0,-1%"

REM Check if git is installed
git --version > nul 2>&1
if %errorlevel% NEQ 0 (
    echo:
    echo No git executable found in PATH!
    echo:
    pause
    exit /b 1
)

REM Create the virtual environment if it doesn't exist
if not exist "%dirpath%\env" (
    echo:
    echo Creating the env folder...
    python -m venv "%dirpath%\env"
    if %errorlevel% NEQ 0 (
        echo:
        echo No python executable found in PATH or failed to create virtual environment!
        echo:
        pause
        exit /b 1
    )
)

REM Activate the virtual environment and install requirements
echo:
echo Installing requirements.txt...
"%dirpath%\env\scripts\python" -m pip install -U pip
"%dirpath%\env\scripts\pip" install wheel
"%dirpath%\env\scripts\pip" install -r "%dirpath%\requirements.txt"
if %errorlevel% NEQ 0 (
    echo:
    echo Failed to install requirements.
    echo:
    pause
    exit /b 1
)

REM Copy .env.example to .env if .env doesn't exist
if not exist "%dirpath%\.env" (
    if exist "%dirpath%\.env.example" (
        echo:
        echo Creating .env from .env.example...
        copy "%dirpath%\.env.example" "%dirpath%\.env" > nul
        echo .env file created successfully.
    ) else (
        echo:
        echo Warning: .env.example not found. Skipping .env creation.
    )
) else (
    echo:
    echo .env file already exists, skipping copy.
)

echo:
echo Generating JWT secret...
"%dirpath%\env\scripts\python" "%dirpath%\generate_jwt_secret.py"

echo:
echo Environment setup completed successfully.
echo:
pause

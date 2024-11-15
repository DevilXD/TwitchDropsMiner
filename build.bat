@echo off

REM Get the directory path of the script
set "dirpath=%~dp0"
if "%dirpath:~-1%" == "\" set "dirpath=%dirpath:~0,-1%"

REM Check if the virtual environment exists
if not exist "%dirpath%\env" (
    echo:
    echo No virtual environment found! Run setup_env.bat to set it up first.
    echo:
    pause
    exit /b
)

REM Check if pyinstaller and pywin32 is installed in the virtual environment
if not exist "%dirpath%\env\scripts\pyinstaller.exe" (
    "%dirpath%\env\scripts\pip" install pyinstaller
    if errorlevel 1 (
        echo Failed to install pyinstaller.
        exit /b 1
    )
    "%dirpath%\env\scripts\python" "%dirpath%\env\scripts\pywin32_postinstall.py" -install -silent
    if errorlevel 1 (
        echo Failed to run pywin32_postinstall.py.
        exit /b 1
    )
)

REM Run pyinstaller with the specified build spec file
"%dirpath%\env\scripts\pyinstaller" "%dirpath%\build.spec"
if errorlevel 1 (
    echo PyInstaller build failed.
    exit /b 1
)

echo Build completed successfully.
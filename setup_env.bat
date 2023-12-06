@echo off
cls
set dirpath=%~dp0
if "%dirpath:~-1%" == "\" set dirpath=%dirpath:~0,-1%

git --version > nul
if %errorlevel% NEQ 0 (
    echo No git executable found in PATH!
    echo:
    pause
    exit
)

if not exist "%dirpath%\env" (
    echo:
    echo Creating the env folder...
    python -m venv "%dirpath%\env"
    if %errorlevel% NEQ 0 (
        echo:
        echo No python executable found in PATH!
        echo:
        pause
    )
)

echo:
echo Installing requirements.txt...
"%dirpath%\env\scripts\python" -m pip install -U pip
"%dirpath%\env\scripts\pip" install wheel
"%dirpath%\env\scripts\pip" install -r "%dirpath%\requirements.txt"

echo:
echo All done!
echo:
pause

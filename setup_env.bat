@echo off
cls
set dirpath=%~dp0
if "%dirpath:~-1%" == "\" set dirpath=%dirpath:~0,-1%
git --version > nul
if %errorlevel% NEQ 0 goto NOGIT
if not exist "%dirpath%\env" (
    echo:
    echo Creating the env folder...
    python -m venv "%dirpath%\env"
    if %errorlevel% NEQ 0 goto NOPYTHON
)
echo:
echo Installing requirements.txt...
"%dirpath%\env\scripts\python" -m pip install -U pip
"%dirpath%\env\scripts\pip" install wheel
"%dirpath%\env\scripts\pip" install -r "%dirpath%\requirements.txt"
goto DONE
:NOPYTHON
echo:
echo No python executable found in path!
pause
goto END
:NOGIT
echo:
echo No git executable found in path!
pause
goto END
:DONE
echo:
echo All done!
pause
:END

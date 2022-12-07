@echo off
cls
set dirpath=%~dp0
if "%dirpath:~-1%" == "\" set dirpath=%dirpath:~0,-1%
if not exist "%dirpath%\env\scripts\pyinstaller.exe" (
    "%dirpath%\env\scripts\pip" install pyinstaller
    "%dirpath%\env\scripts\python" "%dirpath%\env\scripts\pywin32_postinstall.py" -install -silent
)
"%dirpath%/env/scripts/pyinstaller" build.spec

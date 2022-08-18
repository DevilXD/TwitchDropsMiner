@echo off
cls
%CD%/env/scripts/pyinstaller build.spec
if %ERRORLEVEL% == 0 call pack.bat

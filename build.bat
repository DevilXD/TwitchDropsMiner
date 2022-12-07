@echo off
cls
set dirpath=%~dp0
if "%dirpath:~-1%" == "\" set dirpath=%dirpath:~0,-1%
"%dirpath%/env/scripts/pyinstaller" build.spec

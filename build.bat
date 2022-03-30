@echo off
cls
%CD%/env/scripts/pyinstaller --onefile --noconsole --name "Twitch Drops Miner (by DevilXD)" ^
--icon pickaxe.ico --add-data pickaxe.ico;. main.py
if %ERRORLEVEL% == 0 call pack.bat

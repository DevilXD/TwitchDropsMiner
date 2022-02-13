@echo off
cls
pyinstaller --onefile --noconsole --name "Twitch Drops Miner (by DevilXD)" --icon pickaxe.ico ^
--add-data pickaxe.ico;. main.py
call pack.bat

@echo off
IF NOT EXIST 7z.exe GOTO NO7Z
IF NOT EXIST "Twitch Drops Miner" mkdir "Twitch Drops Miner"
rem Prepare files
copy /y /v dist\*.exe "Twitch Drops Miner"
copy /y /v manual.txt "Twitch Drops Miner"
IF EXIST "Twitch Drops Miner.zip" (
    rem Add action
    set action=a
) ELSE (
    rem Update action
    set action=u
)
rem Pack and test
7z %action% "Twitch Drops Miner.zip" "Twitch Drops Miner/" -r
7z t "Twitch Drops Miner.zip" * -r
rem Cleanup
IF EXIST "Twitch Drops Miner" rmdir /s /q "Twitch Drops Miner"
GOTO EXIT
:NO7Z
echo No 7z.exe detected, skipping packaging!
GOTO EXIT
:EXIT
exit %errorlevel%

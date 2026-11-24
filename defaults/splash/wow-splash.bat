@echo off
setlocal
rem WoW Splash plugin. Starts Battle.net. With "launch": asks it to start WoW Forever
rem every ~3s until Wow.exe runs (--exec is ignored on a cold start, so it is sent again).
rem Wine: find /i and find /c break, and Battle.net locks its log, so watch the process list.
set "BNET=C:\Program Files (x86)\Battle.net"
start "" "%BNET%\Battle.net Launcher.exe"
if not "%~1"=="launch" goto done
set /a N=0
:loop
ping -n 4 127.0.0.1 >nul
set /a N+=1
tasklist | find "Wow.exe" >nul
if not errorlevel 1 goto done
if %N% geq 40 goto done
"%BNET%\Battle.net.exe" --exec="launch WoWF"
goto loop
:done

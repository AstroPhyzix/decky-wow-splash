@echo off
setlocal
rem WoW Splash plugin. Starts Battle.net. With "launch": asks it to start WoW Forever
rem every ~3s until Wow.exe runs (--exec is ignored on a cold start, so it is sent again).
rem Wine: find /i and find /c break, and Battle.net locks its log, so watch the process list.
rem Keeps asking for as long as Battle.net is open (a game update of any length must finish
rem first); stops once Battle.net is closed, since --exec would start it again.
rem Battle.net cancels a running update when asked to launch (seen in its Operations log),
rem so nothing is sent while C:\wow-splash-wait exists (the splash removes it).
set "BNET=C:\Program Files (x86)\Battle.net"
start "" "%BNET%\Battle.net Launcher.exe"
if not "%~1"=="launch" goto done
set /a N=0
:loop
ping -n 4 127.0.0.1 >nul
set /a N+=1
tasklist | find "Wow.exe" >nul
if not errorlevel 1 goto done
if %N% geq 10 (
  tasklist | find "Battle.net.exe" >nul
  if errorlevel 1 goto done
)
rem The splash keeps this file while Battle.net checks for or runs a game update/repair:
rem a launch request would cancel it.
if exist "C:\wow-splash-wait" goto loop
"%BNET%\Battle.net.exe" --exec="launch WoWF"
goto loop
:done

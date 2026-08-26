@echo off
taskkill /f /im pythonw.exe >nul 2>&1
taskkill /f /im python.exe /fi "WINDOWTITLE eq Mobile Gamepad*" >nul 2>&1
echo Mobile Gamepad Server detenido.
timeout /t 2 >nul

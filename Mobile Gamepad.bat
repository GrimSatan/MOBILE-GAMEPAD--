@echo off
title Mobile Gamepad Server
cd /d "%~dp0"

:: Verificar Python
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python no encontrado. Instala Python 3.10+ desde python.org
    pause
    exit /b 1
)

:: Instalar dependencias silenciosamente
pip install -r requirements.txt -q 2>nul

:: Ejecutar servidor
python server.py
pause

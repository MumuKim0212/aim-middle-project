@echo off
cd /d "%~dp0"
start "backend" cmd /k run-backend.bat
start "frontend" cmd /k run-frontend.bat

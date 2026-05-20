@echo off
setlocal
title NEXUS — Servidor
color 0A

if not exist "venv\Scripts\activate.bat" (
    echo [ERRO] Venv nao encontrado. Execute install.bat primeiro.
    pause & exit /b 1
)

call venv\Scripts\activate.bat
echo.
echo  NEXUS Robot Contabilistico — a iniciar...
echo  Servidor: http://localhost:5000
echo  Prima Ctrl+C para parar.
echo.

cd backend
python app.py

pause

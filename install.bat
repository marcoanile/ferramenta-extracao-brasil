@echo off
setlocal enabledelayedexpansion
title NEXUS — Instalação
color 0B
echo.
echo  ███╗   ██╗███████╗██╗  ██╗██╗   ██╗███████╗
echo  ████╗  ██║██╔════╝╚██╗██╔╝██║   ██║██╔════╝
echo  ██╔██╗ ██║█████╗   ╚███╔╝ ██║   ██║███████╗
echo  ██║╚██╗██║██╔══╝   ██╔██╗ ██║   ██║╚════██║
echo  ██║ ╚████║███████╗██╔╝ ██╗╚██████╔╝███████║
echo  ╚═╝  ╚═══╝╚══════╝╚═╝  ╚═╝ ╚═════╝ ╚══════╝
echo.
echo  Robot Contabilistico — Instalacao
echo  ==========================================
echo.

:: Check Python
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERRO] Python nao encontrado. Instale Python 3.11+ em https://python.org
    pause & exit /b 1
)
echo [OK] Python encontrado.

:: Create .env from example if not exists
if not exist ".env" (
    copy ".env.example" ".env" >nul
    echo [OK] Ficheiro .env criado. EDITE o .env com as suas credenciais TOConline!
) else (
    echo [OK] Ficheiro .env ja existe.
)

:: Create virtual environment
if not exist "venv" (
    echo [INFO] A criar ambiente virtual Python...
    python -m venv venv
    if errorlevel 1 (echo [ERRO] Falha ao criar venv & pause & exit /b 1)
    echo [OK] Ambiente virtual criado.
) else (
    echo [OK] Ambiente virtual ja existe.
)

:: Install dependencies
echo [INFO] A instalar dependencias Python...
call venv\Scripts\activate.bat
pip install --upgrade pip -q
pip install -r backend\requirements.txt
if errorlevel 1 (echo [ERRO] Falha na instalacao de dependencias & pause & exit /b 1)
echo [OK] Dependencias instaladas.

:: Create data directories
if not exist "data\clients" mkdir data\clients
if not exist "data\templates" mkdir data\templates
if not exist "data\logs" mkdir data\logs
echo [OK] Diretorios de dados criados.

echo.
echo  ==========================================
echo  [SUCESSO] Instalacao concluida!
echo  ==========================================
echo.
echo  PROXIMOS PASSOS:
echo  1. Edite o ficheiro .env com as suas credenciais TOConline
echo     (TOCONLINE_CLIENT_ID e TOCONLINE_CLIENT_SECRET)
echo  2. Execute run.bat para iniciar o servidor
echo  3. Abra http://localhost:5000 no browser
echo.
pause

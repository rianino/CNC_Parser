@echo off
chcp 65001 >nul 2>&1
title Analise de Vetorizacao — SRTAP
cd /d "%~dp0"

echo.
echo   Analise de Vetorizacao — SRTAP
echo   ==============================
echo.

:: -------------------------------------------------------
:: 1. Find Python
:: -------------------------------------------------------
where python >nul 2>&1
if %errorlevel% neq 0 (
    where python3 >nul 2>&1
    if %errorlevel% neq 0 (
        echo   ERRO: Python nao encontrado.
        echo   Instalar Python 3.10+ em https://www.python.org/downloads/
        echo   Marcar "Add Python to PATH" durante a instalacao.
        echo.
        pause
        exit /b 1
    )
    set PYTHON=python3
) else (
    set PYTHON=python
)

:: -------------------------------------------------------
:: 2. Create virtual environment on first run
:: -------------------------------------------------------
if not exist ".venv" (
    echo   A criar ambiente virtual...
    %PYTHON% -m venv .venv
    if %errorlevel% neq 0 (
        echo   ERRO: Nao foi possivel criar ambiente virtual.
        pause
        exit /b 1
    )
)

:: -------------------------------------------------------
:: 3. Activate venv
:: -------------------------------------------------------
call .venv\Scripts\activate.bat

:: -------------------------------------------------------
:: 4. Install / update dependencies on first run or when
::    pyproject.toml is newer than the stamp file
:: -------------------------------------------------------
if not exist ".venv\.deps_installed" (
    echo   A instalar dependencias (primeira execucao)...
    pip install --quiet --upgrade pip
    pip install --quiet -e .
    if %errorlevel% neq 0 (
        echo   ERRO: Falha ao instalar dependencias.
        pause
        exit /b 1
    )
    echo done > .venv\.deps_installed
    echo   Dependencias instaladas.
    echo.
)

:: -------------------------------------------------------
:: 5. Copy .env.example if .env does not exist
:: -------------------------------------------------------
if not exist "app\.env" (
    if exist "app\.env.example" (
        copy "app\.env.example" "app\.env" >nul
        echo   Ficheiro app\.env criado a partir do exemplo.
        echo   Editar app\.env com as credenciais SMTP para enviar emails.
        echo.
    )
)

:: -------------------------------------------------------
:: 6. Launch
:: -------------------------------------------------------
echo   A iniciar servidor...
echo.
set HOST=127.0.0.1
set PORT=5050
python app\server.py
pause

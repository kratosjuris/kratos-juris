@echo off
setlocal EnableExtensions
title Sistema do Escritorio (Servidor)

cd /d "%~dp0"

REM ====== ATIVA VENV ======
IF EXIST "venv\Scripts\activate.bat" (
    call "venv\Scripts\activate.bat"
) ELSE IF EXIST ".venv\Scripts\activate.bat" (
    call ".venv\Scripts\activate.bat"
) ELSE (
    echo ERRO: Nao encontrei venv ou .venv.
    pause
    exit /b 1
)

REM ====== POSTGRESQL (senha com @ precisa virar %40) ======
set "DATABASE_URL=postgresql+psycopg2://escritorio_user:Chris08%%40@192.168.1.10:5432/escritorio"

echo.
echo ==========================================
echo Subindo servidor...
echo URL: http://192.168.1.10:8000
echo ==========================================
echo.

REM ====== SOBE UVICORN EM UMA NOVA JANELA ======
start "Servidor Uvicorn" cmd /k python -m uvicorn app.main:app --host 0.0.0.0 --port 8000

REM ====== ESPERA 2 SEGUNDOS E ABRE O NAVEGADOR (SEM POWERSHELL) ======
timeout /t 2 /nobreak >nul
start "" "http://192.168.1.10:8000"

echo.
echo Se o navegador nao abrir, acesse manualmente:
echo http://192.168.1.10:8000
echo.
pause

endlocal

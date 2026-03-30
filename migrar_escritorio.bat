@echo off
title Migracao Escritório Kratos

echo ========================================
echo INICIANDO MIGRACAO DO ESCRITORIO
echo ========================================

cd /d "D:\PROJETO SISTEMA ESCRITÓRIO\PROJETO SISTEMA CSL"

echo.
echo Ativando ambiente virtual...
call venv\Scripts\activate

echo.
echo Executando script de migracao...
python -m app.scripts.migrate_current_office

echo.
echo ========================================
echo MIGRACAO FINALIZADA
echo ========================================

pause
@echo off
cd /d "D:\PROJETO SISTEMA ESCRITÓRIO\PROJETO SISTEMA CSL"
call venv\Scripts\activate
set DATABASE_URL=
start http://127.0.0.1:8000
uvicorn app.main:app --host 127.0.0.1 --port 8000
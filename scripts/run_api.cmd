@echo off
rem Avast injects SSLKEYLOGFILE globally, which aborts this Python build's TLS
rem (OPENSSL_Applink). Clear it before launching uvicorn.
set SSLKEYLOGFILE=
cd /d "%~dp0.."
venv\Scripts\python.exe -m uvicorn api.main:app --port 8000

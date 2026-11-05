@echo off
cd /d "%~dp0"
docker compose up -d
cd backend
if not exist .venv (
    python -m venv .venv
    call .venv\Scripts\activate
    pip install -r requirements.txt
) else (
    call .venv\Scripts\activate
)
uvicorn app.main:app --reload
pause

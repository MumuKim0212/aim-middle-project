@echo off
cd /d "%~dp0"
cd backend
if not exist .venv (
    python -m venv .venv
    call .venv\Scripts\activate
    pip install -r requirements.txt
) else (
    call .venv\Scripts\activate
    pip install -q -r requirements.txt
)
alembic upgrade head
uvicorn app.main:app --reload
pause

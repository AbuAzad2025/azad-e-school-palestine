@echo off
setlocal
set PYTHONPATH=.
set FLASK_APP=run.py
set FLASK_ENV=development
echo Starting PostgreSQL service...
sc query postgresql-x64-18 >nul 2>&1
if %errorlevel% neq 0 (
    echo PostgreSQL service not found.
    pause
    exit /b 1
)
sc query postgresql-x64-18 | findstr /i "STATE" | findstr /i "RUNNING" >nul 2>&1
if %errorlevel% neq 0 (
    echo Starting PostgreSQL service...
    net start postgresql-x64-18
    if %errorlevel% neq 0 (
        echo Failed to start PostgreSQL. Run as Administrator if needed.
        pause
        exit /b 1
    )
    timeout /t 2 /nobreak >nul
)
echo Running Flask App...
python run.py
pause

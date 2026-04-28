@echo off
setlocal

set BASE=%~dp0
set PGDATA=%BASE%pgdata
set PGPORT=5433
set PGBIN=%BASE%pgsql\bin

echo ============================================================
echo   tatenergo_bdds
echo ============================================================

:: 1. Python check
where python >nul 2>&1
if errorlevel 1 (
    echo ERROR: Python not found in PATH.
    echo Install Python 3.11+ and check "Add to PATH".
    pause
    exit /b 1
)

:: 2. Virtual environment
if not exist "%BASE%venv\Scripts\activate.bat" (
    echo Creating virtual environment...
    python -m venv "%BASE%venv"
    if errorlevel 1 (
        echo ERROR: Failed to create venv.
        pause
        exit /b 1
    )
    echo Installing dependencies...
    "%BASE%venv\Scripts\pip.exe" install -r "%BASE%requirements.txt" --quiet
    if errorlevel 1 (
        echo ERROR: pip install failed.
        pause
        exit /b 1
    )
)

:: 3. PostgreSQL portable check
if not exist "%PGBIN%\pg_ctl.exe" (
    echo ERROR: PostgreSQL not found in pgsql\bin\
    echo Please download portable PostgreSQL and unpack to pgsql\
    echo See README.md for instructions.
    pause
    exit /b 1
)

:: 4. Init PostgreSQL cluster (first run only)
if not exist "%PGDATA%\PG_VERSION" (
    echo Initializing PostgreSQL cluster...
    "%PGBIN%\initdb.exe" -D "%PGDATA%" -U postgres -E UTF8 --no-locale
    if errorlevel 1 (
        echo ERROR: initdb failed.
        pause
        exit /b 1
    )
)

:: 5. Start PostgreSQL if not running
"%PGBIN%\pg_ctl.exe" status -D "%PGDATA%" >nul 2>&1
if errorlevel 1 (
    echo Starting PostgreSQL on port %PGPORT%...
    "%PGBIN%\pg_ctl.exe" start -D "%PGDATA%" -l "%PGDATA%\pg.log" -o "-p %PGPORT%" -w
    if errorlevel 1 (
        echo ERROR: PostgreSQL failed to start.
        echo Check log: %PGDATA%\pg.log
        pause
        exit /b 1
    )
) else (
    echo PostgreSQL already running.
)

:: 6. Init database schema
echo Initializing database...
"%BASE%venv\Scripts\python.exe" "%BASE%init_db.py"
if errorlevel 1 (
    echo ERROR: Database init failed.
    pause
    exit /b 1
)

:: 7. Start FastAPI
echo.
echo Starting application...
echo Open browser: http://127.0.0.1:8000
echo Press Ctrl+C to stop.
echo.

start "" "http://127.0.0.1:8000"

"%BASE%venv\Scripts\uvicorn.exe" app.main:app --host 127.0.0.1 --port 8000 --reload --reload-dir "%BASE%app"

:: Shutdown PostgreSQL when app exits
call "%BASE%stop.bat"

endlocal

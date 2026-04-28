@echo off
setlocal
set BASE=%~dp0
set PGBIN=%BASE%pgsql\bin
set PGDATA=%BASE%pgdata

echo Stopping PostgreSQL...
"%PGBIN%\pg_ctl.exe" stop -D "%PGDATA%" -m fast >nul 2>&1
echo Done.
endlocal

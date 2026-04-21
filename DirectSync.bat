@echo off
REM ===================================================
REM Kobo to Notion - Direct Sync (No USB Monitor)
REM Use this when KoboReader.sqlite is already copied
REM ===================================================

echo Kobo to Notion Direct Sync
echo ============================
echo.

REM Check if Python is installed
python --version >nul 2>&1
if errorlevel 1 (
    echo ERROR: Python is not installed or not in PATH
    pause
    exit /b 1
)

REM Check if KoboReader.sqlite exists
if not exist "KoboReader.sqlite" (
    echo ERROR: KoboReader.sqlite not found!
    echo.
    echo Please copy KoboReader.sqlite from your Kobo device to:
    echo %CD%
    echo.
    echo The file is usually located at:
    echo   [Kobo Drive]\.kobo\KoboReader.sqlite
    pause
    exit /b 1
)

echo Found KoboReader.sqlite
echo Starting sync to Notion...
echo.

python main.py

if errorlevel 1 (
    echo.
    echo ERROR: Sync failed. Check logs/kobo_notion_sync.log for details
    pause
    exit /b 1
) else (
    echo.
    echo SUCCESS: All highlights synced to Notion!
    timeout /t 3 /nobreak >nul
)

pause

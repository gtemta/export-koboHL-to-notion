@echo off
REM ===================================================
REM Kobo to Notion Sync - USB Monitor and Upload
REM ===================================================

echo Starting Kobo to Notion sync process...
echo.

REM Check if Python is installed
python --version >nul 2>&1
if errorlevel 1 (
    echo ERROR: Python is not installed or not in PATH
    echo Please install Python 3.x from https://www.python.org/
    pause
    exit /b 1
)

REM Check if checkUSBandUpload.py exists
if not exist "checkUSBandUpload.py" (
    echo ERROR: checkUSBandUpload.py not found in current directory
    echo Current directory: %CD%
    pause
    exit /b 1
)

REM Check if KoboReader.sqlite exists (optional - for direct sync)
if exist "KoboReader.sqlite" (
    echo Found KoboReader.sqlite in current directory
    echo Running direct sync...
    python main.py
) else (
    echo KoboReader.sqlite not found, starting USB monitor...
    echo Please connect your Kobo device
    echo.
    python checkUSBandUpload.py
)

REM Check exit code
if errorlevel 1 (
    echo.
    echo ERROR: Sync process failed. Check usb_monitor.log for details
    pause
    exit /b 1
) else (
    echo.
    echo SUCCESS: Sync completed successfully!
    timeout /t 3 /nobreak >nul
)

pause
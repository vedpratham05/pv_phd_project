@echo off
REM ============================================================
REM  Campus eKYC & Security Console - ONE-CLICK WINDOWS SETUP
REM  Double-click this file on a fresh Windows laptop.
REM  It will:
REM    1. Install Python 3.11 automatically if missing
REM    2. Create the virtual environment (venv)
REM    3. Download + install every dependency (YOLO, OpenCV,
REM       face_recognition, FastAPI, Flask, Twilio, ...)
REM    4. Create START_PROJECT.bat for daily one-click launch
REM ============================================================
setlocal EnableDelayedExpansion
title Campus eKYC - One-Time Setup
cd /d "%~dp0"

echo.
echo  ==========================================================
echo   CAMPUS eKYC ^& SECURITY CONSOLE  -  ONE-TIME SETUP
echo  ==========================================================
echo.

REM ---------- STEP 1: Python 3.11 ----------
echo [1/4] Checking for Python 3.11 (64-bit)...
py -3.11 --version >nul 2>&1
if not errorlevel 1 goto have_python

echo       Python 3.11 not found. Installing it now...
echo       (trying winget first, then direct download)

winget install -e --id Python.Python.3.11 --silent --accept-package-agreements --accept-source-agreements >nul 2>&1

py -3.11 --version >nul 2>&1
if not errorlevel 1 goto have_python

echo       winget unavailable - downloading the official installer...
powershell -NoProfile -ExecutionPolicy Bypass -Command "Invoke-WebRequest -Uri 'https://www.python.org/ftp/python/3.11.9/python-3.11.9-amd64.exe' -OutFile \"$env:TEMP\python311setup.exe\""
if errorlevel 1 (
    echo.
    echo  [ERROR] Could not download Python. Check your internet connection,
    echo          then run this file again.
    pause
    exit /b 1
)
echo       Installing Python 3.11 (this takes a minute)...
"%TEMP%\python311setup.exe" /quiet InstallAllUsers=0 PrependPath=1 Include_launcher=1 Include_pip=1
del "%TEMP%\python311setup.exe" >nul 2>&1

py -3.11 --version >nul 2>&1
if errorlevel 1 (
    echo.
    echo  [!] Python was installed but this window can't see it yet.
    echo      CLOSE this window and DOUBLE-CLICK SETUP_WINDOWS.bat AGAIN.
    pause
    exit /b 1
)

:have_python
for /f "tokens=*" %%v in ('py -3.11 --version') do echo       Found: %%v
echo.

REM ---------- STEP 2: Virtual environment ----------
echo [2/4] Creating virtual environment (venv)...
if exist "venv\Scripts\python.exe" (
    echo       venv already exists - reusing it.
) else (
    py -3.11 -m venv venv
    if errorlevel 1 (
        echo  [ERROR] Failed to create the virtual environment.
        pause
        exit /b 1
    )
)
echo.

REM ---------- STEP 3: Install all dependencies ----------
echo [3/4] Downloading and installing ALL packages...
echo       (YOLOv8, OpenCV, face_recognition, FastAPI, Flask, Twilio...)
echo       First time takes 5-15 minutes depending on internet speed.
echo.
venv\Scripts\python.exe -m pip install --upgrade pip
venv\Scripts\python.exe -m pip install -r fastapi_backend\requirements.txt
if errorlevel 1 goto pip_failed
venv\Scripts\python.exe -m pip install -r requirements.txt
if errorlevel 1 goto pip_failed
echo.
echo       All packages installed OK.
echo.

REM ---------- STEP 4: Create the daily launcher ----------
echo [4/4] Creating START_PROJECT.bat ...
(
echo @echo off
echo title Campus eKYC - Launcher
echo cd /d "%%~dp0"
echo echo Starting backend ^(port 8000^) + camera bridge...
echo start "eKYC Backend (8000)" cmd /k "cd /d %%~dp0fastapi_backend && ..\venv\Scripts\python.exe -m uvicorn main:app --reload"
echo timeout /t 6 /nobreak ^>nul
echo echo Starting frontend ^(port 5000^)...
echo start "eKYC Frontend (5000)" cmd /k "cd /d %%~dp0 && venv\Scripts\python.exe app.py"
echo timeout /t 4 /nobreak ^>nul
echo echo Opening the console in your browser...
echo start http://127.0.0.1:5000
echo exit
) > START_PROJECT.bat

echo.
echo  ==========================================================
echo   SETUP COMPLETE!
echo  ==========================================================
echo.
echo   Daily use:  double-click  START_PROJECT.bat
echo   It opens the backend, the camera bridge, the frontend,
echo   and your browser at http://127.0.0.1:5000
echo.
echo   Phone cameras: install "IP Webcam" on the Android phones,
echo   connect them to the SAME WiFi, tap "Start server" - they
echo   are detected automatically within ~20 seconds.
echo.
echo   IMPORTANT: when Windows Firewall asks, click ALLOW
echo   (Private networks) so the phones can be discovered.
echo.
choice /c YN /m "Start the project now"
if errorlevel 2 goto done
call START_PROJECT.bat

:done
echo.
pause
exit /b 0

:pip_failed
echo.
echo  [ERROR] Package installation failed.
echo  Most common cause: wrong Python version (needs 3.11).
echo  Delete the "venv" folder and run this file again.
echo  If it still fails, check your internet connection.
pause
exit /b 1

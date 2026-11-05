@echo off
setlocal
cd /d "%~dp0"
title SSV DELTA - Premium Bearish Scanner
color 0B
echo.
echo  ======================================================
echo      SSV DELTA  ^|  PREMIUM BEARISH SCANNER
 echo  ======================================================
echo.
where py >nul 2>nul
if %errorlevel%==0 (set "PY=py -3") else (set "PY=python")
if not exist ".venv\Scripts\python.exe" (
    echo  Creating local Python environment...
    %PY% -m venv .venv
    if errorlevel 1 goto :fail
)
set "LOCALPY=.venv\Scripts\python.exe"
"%LOCALPY%" -c "import fastapi,uvicorn,httpx" >nul 2>nul
if errorlevel 1 (
    echo  Installing required packages. Internet is needed once...
    "%LOCALPY%" -m pip install -r requirements.txt
    if errorlevel 1 goto :fail
)
echo  Starting dashboard at http://127.0.0.1:8765
echo  Keep this window open while scanning.
echo  Press Ctrl+C here to stop the scanner.
echo.
start "" "http://127.0.0.1:8765"
"%LOCALPY%" -m uvicorn app:app --host 127.0.0.1 --port 8765
echo.
echo  Scanner stopped. Press any key to close.
pause >nul
exit /b 0
:fail
echo.
echo  Setup failed. Check that Python is installed and internet is available.
pause
exit /b 1

@echo off
cd /d "%~dp0"
if not defined PORT set PORT=5001
python -c "import flask" >nul 2>&1
if errorlevel 1 python -m pip install -r requirements.txt
echo.
echo Future Self: http://127.0.0.1:%PORT%
echo Press Ctrl+C to stop.
echo.
python app.py
pause

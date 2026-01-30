@echo off
echo ============================================
echo Cell Scheduling Engine - Web Interface
echo Version 1.0.0
echo ============================================
echo.

:: Check Python
python --version >nul 2>&1
if errorlevel 1 (
    echo ERROR: Python not found
    pause
    exit /b 1
)

:: Check dependencies
echo Checking dependencies...
python -c "import ortools" 2>nul
if errorlevel 1 (
    echo Installing ortools...
    pip install ortools
)

python -c "import openpyxl" 2>nul
if errorlevel 1 (
    echo Installing openpyxl...
    pip install openpyxl
)

python -c "import yaml" 2>nul
if errorlevel 1 (
    echo Installing pyyaml...
    pip install pyyaml
)

python -c "import reportlab" 2>nul
if errorlevel 1 (
    echo Installing reportlab...
    pip install reportlab
)

python -c "import fastapi" 2>nul
if errorlevel 1 (
    echo Installing fastapi...
    pip install fastapi
)

python -c "import uvicorn" 2>nul
if errorlevel 1 (
    echo Installing uvicorn...
    pip install uvicorn
)

:: Check config file
if not exist "config\constants.yaml" (
    echo ERROR: config\constants.yaml not found
    pause
    exit /b 1
)

echo.
echo Starting web server...
echo.
echo ============================================
echo Open your browser to: http://localhost:8000
echo Press Ctrl+C to stop the server
echo ============================================
echo.

python -m uvicorn web.app:app --host 0.0.0.0 --port 8000 --reload

:end

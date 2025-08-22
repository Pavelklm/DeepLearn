@echo off
echo Checking Python installation...
echo.

python --version 2>nul
if errorlevel 1 (
    echo Python is NOT installed or not in PATH
    echo.
    echo Please install Python from: https://www.python.org/downloads/
    echo Make sure to check "Add Python to PATH" during installation
) else (
    echo Python found!
    python --version
    echo.
    echo Installing dependencies...
    pip install requests
    if errorlevel 1 (
        echo Failed to install requests
    ) else (
        echo.
        echo Starting scanner...
        python big_orders_scanner.py
    )
)

echo.
pause

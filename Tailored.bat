@echo off
setlocal EnableDelayedExpansion
title Tailored
chcp 65001 >nul
cd /d "%~dp0"

set "SETUP_ONLY=0"
set "FORCE_CLEAN=0"
if /i "%~1"=="setup" set "SETUP_ONLY=1"
if /i "%~1"=="--clean" set "FORCE_CLEAN=1"
if /i "%~1"=="clean" set "FORCE_CLEAN=1"

rem ---------------------------------------------------------------------
rem 1. Find a Python 3.11+ interpreter.
rem ---------------------------------------------------------------------
set "PYTHON_EXE="

python -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)" >nul 2>&1
if %errorlevel%==0 set "PYTHON_EXE=python"

if not defined PYTHON_EXE (
    py -3 -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)" >nul 2>&1
    if !errorlevel!==0 set "PYTHON_EXE=py -3"
)

if not defined PYTHON_EXE (
    echo.
    echo Tailored needs Python 3.11 or newer, and it could not be found on this computer.
    echo.
    echo Please install Python 3.11+ from python.org.
    echo IMPORTANT: on the first install screen, CHECK "Add python.exe to PATH".
    echo.
    echo Opening the download page for you...
    start "" "https://www.python.org/downloads/"
    if "%SETUP_ONLY%"=="0" pause
    exit /b 1
)

rem ---------------------------------------------------------------------
rem 2. Create or recover the virtual environment.
rem ---------------------------------------------------------------------
set "VENV_CORRUPT=0"
if exist ".venv\Scripts\python.exe" (
    rem Test if venv is usable by trying to import a basic module
    ".venv\Scripts\python.exe" -c "import sys; sys.exit(0)" >nul 2>&1
    if errorlevel 1 (
        set "VENV_CORRUPT=1"
        echo.
        echo WARNING: Virtual environment appears to be corrupted. Rebuilding...
        echo.
    )
)

if "%FORCE_CLEAN%"=="1" (
    echo Removing old virtual environment...
    rmdir /s /q ".venv" 2>nul
    set "VENV_CORRUPT=0"
)

if "%VENV_CORRUPT%"=="1" (
    echo Removing corrupted virtual environment...
    rmdir /s /q ".venv" 2>nul
)

if not exist ".venv\Scripts\python.exe" (
    echo First-time setup - creating Python virtual environment...
    echo This takes a few moments...
    echo.
    %PYTHON_EXE% -m venv ".venv"
    if errorlevel 1 (
        echo.
        echo ERROR: Failed to create the Python virtual environment.
        echo.
        echo Troubleshooting steps:
        echo   1. Make sure Python 3.11+ is properly installed
        echo   2. Try running as Administrator
        echo   3. Run: %PYTHON_EXE% -m venv ".venv" for more details
        echo.
        if "%SETUP_ONLY%"=="0" pause
        exit /b 1
    )
)

rem ---------------------------------------------------------------------
rem 3. Upgrade pip and install/update dependencies.
rem ---------------------------------------------------------------------
set "NEED_DEPS=0"
if not exist ".venv\.deps-installed" (
    set "NEED_DEPS=1"
) else (
    fc /b "requirements.txt" ".venv\.deps-installed" >nul 2>&1
    if errorlevel 1 set "NEED_DEPS=1"
)

if "%NEED_DEPS%"=="1" (
    echo.
    echo Upgrading pip and installing dependencies...
    echo This can take a few minutes on first run...
    echo.

    rem Upgrade pip first to avoid conflicts
    ".venv\Scripts\python.exe" -m pip install --upgrade pip setuptools wheel >nul 2>&1

    rem Install requirements
    ".venv\Scripts\python.exe" -m pip install -r requirements.txt
    if errorlevel 1 (
        echo.
        echo ERROR: Failed to install dependencies.
        echo.
        echo Troubleshooting:
        echo   1. Check the error message above for details
        echo   2. Try running: Tailored.bat --clean
        echo   3. If that fails, try running as Administrator
        echo   4. Or manually run:
        echo      ".venv\Scripts\python.exe" -m pip install -r requirements.txt
        echo.
        if "%SETUP_ONLY%"=="0" pause
        exit /b 1
    )
    copy /y "requirements.txt" ".venv\.deps-installed" >nul
    echo Dependencies installed successfully.
)

rem ---------------------------------------------------------------------
rem 4. Install the Chromium browser used for PDF export (best-effort).
rem ---------------------------------------------------------------------
if not exist ".venv\.chromium-installed" (
    echo.
    echo Installing the Chromium browser for PDF export...
    echo This can take a minute on first run...
    echo.
    ".venv\Scripts\python.exe" -m playwright install chromium >nul 2>&1
    if errorlevel 1 (
        echo.
        echo WARNING: Chromium install failed - PDF export won't work until fixed.
        echo You can install it manually later by running:
        echo   ".venv\Scripts\python.exe" -m playwright install chromium
        echo.
        echo Continuing without it for now...
        echo.
    ) else (
        echo done > ".venv\.chromium-installed"
        echo Chromium installed successfully.
    )
)

rem ---------------------------------------------------------------------
rem 5. Make sure there's a usable API key, or fall back to demo mode.
rem ---------------------------------------------------------------------
call :check_key
if not errorlevel 1 goto :have_key_or_demo

if not exist ".env" (
    if exist ".env.example" copy ".env.example" ".env" >nul
)

if "%SETUP_ONLY%"=="1" (
    echo Setup complete.
    exit /b 0
)

set "KEY_ATTEMPTS=0"

:menu
echo.
echo No Anthropic API key found yet.
echo   [1] Add my Anthropic API key now (opens Notepad)
echo   [2] Try it in demo mode (no key needed, sample data)
echo   [3] Exit
set "MENU_CHOICE="
set /p "MENU_CHOICE=Choose 1, 2, or 3: "

if "%MENU_CHOICE%"=="1" (
    start /wait notepad ".env"
    call :check_key
    if not errorlevel 1 goto :have_key_or_demo
    set /a KEY_ATTEMPTS+=1
    if !KEY_ATTEMPTS! GEQ 2 (
        echo.
        echo Still no key found - starting in demo mode instead.
        set "TAILORED_FAKE=1"
        goto :have_key_or_demo
    )
    goto :menu
)

if "%MENU_CHOICE%"=="2" (
    set "TAILORED_FAKE=1"
    goto :have_key_or_demo
)

if "%MENU_CHOICE%"=="3" (
    exit /b 0
)

echo Please enter 1, 2, or 3.
goto :menu

:have_key_or_demo
if "%SETUP_ONLY%"=="1" (
    echo Setup complete.
    exit /b 0
)

rem ---------------------------------------------------------------------
rem 6. Launch.
rem ---------------------------------------------------------------------
echo.
echo Starting Tailored...
echo.
".venv\Scripts\python.exe" "run.py"
set "RC=%errorlevel%"
if not "%RC%"=="0" (
    echo.
    echo ERROR: Tailored stopped with an error. Check the message above.
    echo.
    echo Quick troubleshooting:
    echo   - Try running: Tailored.bat --clean
    echo   - Check that .env has a valid ANTHROPIC_API_KEY, or delete .env to use demo mode
    echo   - Try running as Administrator
    echo   - Check Python 3.11+ is installed: python --version
    echo.
    if "%SETUP_ONLY%"=="0" pause
)
exit /b %RC%

rem ---------------------------------------------------------------------
rem Subroutines
rem ---------------------------------------------------------------------
:check_key
".venv\Scripts\python.exe" -c "import os, sys; from dotenv import load_dotenv; load_dotenv(); key = os.environ.get('ANTHROPIC_API_KEY', '').strip(); fake = os.environ.get('TAILORED_FAKE', ''); sys.exit(0 if (key or fake == '1') else 1)"
exit /b %errorlevel%

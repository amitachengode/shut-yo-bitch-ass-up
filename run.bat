@echo off
setlocal enabledelayedexpansion

:: ClickChaos Windows Batch Launcher
:: 1. Detects Python package manager
:: 2. Creates virtual environment if missing
:: 3. Installs dependencies
:: 4. Activates environment and runs ClickChaos

cd /d "%~dp0"
echo ===================================================
echo             ClickChaos Runner (Windows)
echo ===================================================

set "PKG_MGR="
set "PYTHON_CMD="

:: ----------------------------------------------------
:: 1. Detect Python Package Managers
:: ----------------------------------------------------
echo [1/4] Detecting Python package managers...

:: Check for uv (Highest priority: fastest modern package manager)
where uv >nul 2>nul
if %errorlevel% equ 0 (
    set "PKG_MGR=uv"
    set "PYTHON_CMD=uv run python"
    echo   [+] Found: uv [Ultra-fast Python package manager]
    goto :pkg_detected
)

:: Check for Python with pip module
where python >nul 2>nul
if %errorlevel% equ 0 (
    python -m pip --version >nul 2>nul
    if !errorlevel! equ 0 (
        set "PKG_MGR=pip"
        set "PYTHON_CMD=python"
        echo   [+] Found: python with pip
        goto :pkg_detected
    )
)

:: Check for Windows Python Launcher (py) with pip
where py >nul 2>nul
if %errorlevel% equ 0 (
    py -m pip --version >nul 2>nul
    if !errorlevel! equ 0 (
        set "PKG_MGR=pip"
        set "PYTHON_CMD=py"
        echo   [+] Found: py launcher with pip
        goto :pkg_detected
    )
)

:: Check for Poetry
where poetry >nul 2>nul
if %errorlevel% equ 0 (
    set "PKG_MGR=poetry"
    set "PYTHON_CMD=poetry run python"
    echo   [+] Found: poetry
    goto :pkg_detected
)

:: Check for Pipenv
where pipenv >nul 2>nul
if %errorlevel% equ 0 (
    set "PKG_MGR=pipenv"
    set "PYTHON_CMD=pipenv run python"
    echo   [+] Found: pipenv
    goto :pkg_detected
)

:: Check for Conda / Mamba
where conda >nul 2>nul
if %errorlevel% equ 0 (
    set "PKG_MGR=conda"
    set "PYTHON_CMD=conda run python"
    echo   [+] Found: conda
    goto :pkg_detected
)

:: ----------------------------------------------------
:: No Package Manager Found - Provide Download Links
:: ----------------------------------------------------
echo.
echo [ERROR] No supported Python package manager was detected on this system!
echo.
echo Please install Python or one of the following recommended package managers:
echo.
echo   1. uv (Recommended - ultra-fast installation):
echo      Command: powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
echo      Website: https://docs.astral.sh/uv/getting-started/installation/
echo.
echo   2. Official Python (includes pip and venv):
echo      Download: https://www.python.org/downloads/
echo      * IMPORTANT: Check the box "Add python.exe to PATH" during installation.
echo.
echo   3. Poetry:
echo      Website: https://python-poetry.org/docs/#installation
echo.
echo   4. Miniconda / Anaconda:
echo      Website: https://docs.conda.io/en/latest/miniconda.html
echo.
echo ===================================================
pause
exit /b 1

:pkg_detected
echo   [*] Selected package manager: !PKG_MGR!
echo.

:: ----------------------------------------------------
:: 2. Check / Create Virtual Environment
:: ----------------------------------------------------
echo [2/4] Checking virtual environment...

set "VENV_DIR=.venv"
set "VENV_PY=%VENV_DIR%\Scripts\python.exe"
set "VENV_ACTIVATE=%VENV_DIR%\Scripts\activate.bat"

if exist "%VENV_PY%" (
    "%VENV_PY%" -c "import sys" >nul 2>nul
    if !errorlevel! equ 0 (
        echo   [+] Compatible virtual environment found in "%VENV_DIR%".
        goto :venv_ready
    )
)

echo   [-] No compatible virtual environment found. Creating in "%VENV_DIR%"...

if "!PKG_MGR!"=="uv" (
    uv venv "%VENV_DIR%"
    if !errorlevel! neq 0 (
        echo [ERROR] Failed to create virtual environment with uv.
        pause
        exit /b 1
    )
) else if "!PKG_MGR!"=="pip" (
    !PYTHON_CMD! -m venv "%VENV_DIR%"
    if !errorlevel! neq 0 (
        echo [ERROR] Failed to create virtual environment with python -m venv.
        pause
        exit /b 1
    )
) else if "!PKG_MGR!"=="poetry" (
    poetry env use python
) else if "!PKG_MGR!"=="conda" (
    call conda create -y -p "%VENV_DIR%" python=3.11
) else (
    python -m venv "%VENV_DIR%"
)

if not exist "%VENV_PY%" (
    echo [ERROR] Virtual environment creation could not be verified.
    pause
    exit /b 1
)
echo   [+] Virtual environment successfully created.

:venv_ready
echo.

:: ----------------------------------------------------
:: 3. Verify and Install Dependencies
:: ----------------------------------------------------
echo [3/4] Verifying dependencies...

"%VENV_PY%" -c "import pystray, PIL" >nul 2>nul
if %errorlevel% equ 0 (
    echo   [+] Core dependencies [pystray, pillow] are already installed.
) else (
    echo   [-] Missing dependencies. Installing from requirements.txt...
    if "!PKG_MGR!"=="uv" (
        uv pip install -r requirements.txt --python "%VENV_PY%"
    ) else (
        "%VENV_PY%" -m pip install -r requirements.txt
    )
    if !errorlevel! neq 0 (
        echo [ERROR] Failed to install dependencies.
        pause
        exit /b 1
    )
    echo   [+] Dependencies installed successfully.
)
echo.

:: ----------------------------------------------------
:: 4. Activate Virtual Environment and Run ClickChaos
:: ----------------------------------------------------
echo [4/4] Activating virtual environment and launching ClickChaos...
echo ---------------------------------------------------

if exist "%VENV_ACTIVATE%" (
    call "%VENV_ACTIVATE%"
    python main.py %*
) else (
    "%VENV_PY%" main.py %*
)

set "RUN_EXIT_CODE=%errorlevel%"
if %RUN_EXIT_CODE% neq 0 (
    echo.
    echo [ClickChaos exited with code %RUN_EXIT_CODE%]
    pause
)

exit /b %RUN_EXIT_CODE%

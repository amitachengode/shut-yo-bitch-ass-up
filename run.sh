#!/usr/bin/env bash
# ==============================================================================
# ClickChaos Runner (Bash / Linux / macOS / Git Bash)
# 1. Detects Python package manager (uv, pip, poetry, pipenv, conda)
# 2. Creates virtual environment if missing (skips if compatible venv exists)
# 3. Installs dependencies
# 4. Activates environment and runs ClickChaos
# ==============================================================================

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "==================================================="
echo "            ClickChaos Runner (Bash)"
echo "==================================================="

PKG_MGR=""
PYTHON_CMD=""

# ------------------------------------------------------------------------------
# 1. Detect Python Package Managers
# ------------------------------------------------------------------------------
echo "[1/4] Detecting Python package managers..."

check_cmd() {
    command -v "$1" >/dev/null 2>&1 || command -v "$1.exe" >/dev/null 2>&1
}

get_cmd() {
    if command -v "$1" >/dev/null 2>&1; then
        echo "$1"
    elif command -v "$1.exe" >/dev/null 2>&1; then
        echo "$1.exe"
    fi
}

# Check for uv (Highest priority: fastest modern package manager)
if check_cmd uv; then
    UV_BIN="$(get_cmd uv)"
    PKG_MGR="uv"
    PYTHON_CMD="$UV_BIN run python"
    echo "  [+] Found: $UV_BIN [Ultra-fast Python package manager]"
elif check_cmd python3 && "$(get_cmd python3)" -m pip --version >/dev/null 2>&1; then
    PY3_BIN="$(get_cmd python3)"
    PKG_MGR="pip"
    PYTHON_CMD="$PY3_BIN"
    echo "  [+] Found: $PY3_BIN with pip"
elif check_cmd python && "$(get_cmd python)" -m pip --version >/dev/null 2>&1; then
    PY_BIN="$(get_cmd python)"
    PKG_MGR="pip"
    PYTHON_CMD="$PY_BIN"
    echo "  [+] Found: $PY_BIN with pip"
elif check_cmd py && "$(get_cmd py)" -m pip --version >/dev/null 2>&1; then
    PYL_BIN="$(get_cmd py)"
    PKG_MGR="pip"
    PYTHON_CMD="$PYL_BIN"
    echo "  [+] Found: $PYL_BIN launcher with pip"
elif check_cmd poetry; then
    POE_BIN="$(get_cmd poetry)"
    PKG_MGR="poetry"
    PYTHON_CMD="$POE_BIN run python"
    echo "  [+] Found: $POE_BIN"
elif check_cmd pipenv; then
    PIPENV_BIN="$(get_cmd pipenv)"
    PKG_MGR="pipenv"
    PYTHON_CMD="$PIPENV_BIN run python"
    echo "  [+] Found: $PIPENV_BIN"
elif check_cmd conda; then
    CONDA_BIN="$(get_cmd conda)"
    PKG_MGR="conda"
    PYTHON_CMD="$CONDA_BIN run python"
    echo "  [+] Found: $CONDA_BIN"
fi

# ------------------------------------------------------------------------------
# No Package Manager Found - Provide Download Links
# ------------------------------------------------------------------------------
if [ -z "$PKG_MGR" ]; then
    echo ""
    echo "[ERROR] No supported Python package manager was detected on this system!"
    echo ""
    echo "Please install Python or one of the following recommended package managers:"
    echo ""
    echo "  1. uv (Recommended - ultra-fast installation):"
    echo "     Install (Linux/macOS/Git Bash): curl -LsSf https://astral.sh/uv/install.sh | sh"
    echo "     Install (Windows PowerShell):  powershell -ExecutionPolicy ByPass -c \"irm https://astral.sh/uv/install.ps1 | iex\""
    echo "     Website: https://docs.astral.sh/uv/getting-started/installation/"
    echo ""
    echo "  2. Official Python (includes pip and venv):"
    echo "     Download: https://www.python.org/downloads/"
    echo "     * On Windows, make sure to check 'Add python.exe to PATH'."
    echo ""
    echo "  3. Poetry:"
    echo "     Website: https://python-poetry.org/docs/#installation"
    echo ""
    echo "  4. Miniconda / Anaconda:"
    echo "     Website: https://docs.conda.io/en/latest/miniconda.html"
    echo ""
    echo "==================================================="
    exit 1
fi

echo "  [*] Selected package manager: $PKG_MGR"
echo ""

# ------------------------------------------------------------------------------
# 2. Check / Create Virtual Environment
# ------------------------------------------------------------------------------
echo "[2/4] Checking virtual environment..."

VENV_DIR=".venv"
VENV_PY=""
VENV_ACTIVATE=""

# Detect layout: Windows (Scripts) vs Unix (bin)
if [ -f "$VENV_DIR/Scripts/python.exe" ]; then
    VENV_PY="$VENV_DIR/Scripts/python.exe"
    VENV_ACTIVATE="$VENV_DIR/Scripts/activate"
elif [ -f "$VENV_DIR/bin/python" ]; then
    VENV_PY="$VENV_DIR/bin/python"
    VENV_ACTIVATE="$VENV_DIR/bin/activate"
elif [ -f "$VENV_DIR/Scripts/python" ]; then
    VENV_PY="$VENV_DIR/Scripts/python"
    VENV_ACTIVATE="$VENV_DIR/Scripts/activate"
fi

if [ -n "$VENV_PY" ] && "$VENV_PY" -c "import sys" >/dev/null 2>&1; then
    echo "  [+] Compatible virtual environment found in '$VENV_DIR'."
else
    echo "  [-] No compatible virtual environment found. Creating in '$VENV_DIR'..."
    case "$PKG_MGR" in
        uv)
            uv venv "$VENV_DIR"
            ;;
        pip)
            $PYTHON_CMD -m venv "$VENV_DIR"
            ;;
        poetry)
            poetry env use python
            ;;
        pipenv)
            pipenv --three
            ;;
        conda)
            conda create -y -p "$VENV_DIR" python=3.11
            ;;
        *)
            python3 -m venv "$VENV_DIR" || python -m venv "$VENV_DIR"
            ;;
    esac

    # Re-detect created virtual environment paths
    if [ -f "$VENV_DIR/Scripts/python.exe" ]; then
        VENV_PY="$VENV_DIR/Scripts/python.exe"
        VENV_ACTIVATE="$VENV_DIR/Scripts/activate"
    elif [ -f "$VENV_DIR/bin/python" ]; then
        VENV_PY="$VENV_DIR/bin/python"
        VENV_ACTIVATE="$VENV_DIR/bin/activate"
    elif [ -f "$VENV_DIR/Scripts/python" ]; then
        VENV_PY="$VENV_DIR/Scripts/python"
        VENV_ACTIVATE="$VENV_DIR/Scripts/activate"
    fi

    if [ -z "$VENV_PY" ] || ! "$VENV_PY" -c "import sys" >/dev/null 2>&1; then
        echo "[ERROR] Virtual environment creation failed or python executable was not found."
        exit 1
    fi
    echo "  [+] Virtual environment successfully created."
fi

echo ""

# ------------------------------------------------------------------------------
# 3. Verify and Install Dependencies
# ------------------------------------------------------------------------------
echo "[3/4] Verifying dependencies..."

if "$VENV_PY" -c "import pystray, PIL" >/dev/null 2>&1; then
    echo "  [+] Core dependencies (pystray, pillow) are already installed."
else
    echo "  [-] Missing dependencies. Installing from requirements.txt..."
    if [ "$PKG_MGR" = "uv" ]; then
        uv pip install -r requirements.txt --python "$VENV_PY"
    else
        "$VENV_PY" -m pip install -r requirements.txt
    fi
    echo "  [+] Dependencies installed successfully."
fi

echo ""

# ------------------------------------------------------------------------------
# 4. Activate Virtual Environment and Run ClickChaos
# ------------------------------------------------------------------------------
echo "[4/4] Activating virtual environment and launching ClickChaos..."
echo "---------------------------------------------------"

if [ -f "$VENV_ACTIVATE" ]; then
    # shellcheck disable=SC1090
    source "$VENV_ACTIVATE" 2>/dev/null || true
fi

"$VENV_PY" main.py "$@"

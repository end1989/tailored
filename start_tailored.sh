#!/usr/bin/env bash
# Tailored launcher for macOS / Linux.
#
# Usage: bash start_tailored.sh
#        bash start_tailored.sh setup   (runs setup only, no launch; for tests)
set -euo pipefail

cd "$(dirname "$0")"

SETUP_ONLY=0
if [ "${1:-}" = "setup" ]; then
    SETUP_ONLY=1
fi

check_version() {
    "$1" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)' >/dev/null 2>&1
}

# ---------------------------------------------------------------------
# 1. Find a Python 3.11+ interpreter.
# ---------------------------------------------------------------------
PYTHON_BIN=""
if command -v python3 >/dev/null 2>&1 && check_version python3; then
    PYTHON_BIN="python3"
elif command -v python >/dev/null 2>&1 && check_version python; then
    PYTHON_BIN="python"
fi

if [ -z "$PYTHON_BIN" ]; then
    echo ""
    echo "Tailored needs Python 3.11 or newer, and it could not be found on this computer."
    echo ""
    case "$(uname -s)" in
        Darwin*)
            echo "Install it with Homebrew:  brew install python@3.12"
            echo "or download it from:       https://www.python.org/downloads/macos/"
            ;;
        *)
            echo "Install it with your package manager, for example:"
            echo "  sudo apt install python3.12 python3.12-venv   # Debian/Ubuntu"
            echo "  sudo dnf install python3.12                   # Fedora"
            echo "or download it from: https://www.python.org/downloads/"
            ;;
    esac
    echo ""
    exit 1
fi

# ---------------------------------------------------------------------
# 2. Create the virtual environment if it doesn't exist yet.
# ---------------------------------------------------------------------
VENV_DIR=".venv"
VENV_PY="$VENV_DIR/bin/python"

if [ ! -x "$VENV_PY" ]; then
    echo "First-time setup - this takes a few minutes..."
    "$PYTHON_BIN" -m venv "$VENV_DIR"
fi

# ---------------------------------------------------------------------
# 3. Install/update dependencies if requirements.txt changed.
# ---------------------------------------------------------------------
DEPS_MARKER="$VENV_DIR/.deps-installed"
NEED_DEPS=1
if [ -f "$DEPS_MARKER" ] && cmp -s "requirements.txt" "$DEPS_MARKER"; then
    NEED_DEPS=0
fi

if [ "$NEED_DEPS" = "1" ]; then
    echo "Installing dependencies - this can take a few minutes on first run..."
    if ! "$VENV_PY" -m pip install -r requirements.txt; then
        echo ""
        echo "Failed to install dependencies. Check the error above, then re-run this script."
        exit 1
    fi
    cp "requirements.txt" "$DEPS_MARKER"
fi

# ---------------------------------------------------------------------
# 4. Install the Chromium browser used for PDF export (best-effort).
# ---------------------------------------------------------------------
CHROMIUM_MARKER="$VENV_DIR/.chromium-installed"
if [ ! -f "$CHROMIUM_MARKER" ]; then
    echo "Installing the Chromium browser for PDF export - this can take a minute..."
    if "$VENV_PY" -m playwright install chromium; then
        echo "done" > "$CHROMIUM_MARKER"
    else
        echo ""
        echo "WARNING: Chromium install failed - PDF export won't work until you run:"
        echo "  $VENV_PY -m playwright install chromium"
        echo "Continuing without it..."
        echo ""
    fi
fi

# ---------------------------------------------------------------------
# 5. Make sure there's a usable API key, or fall back to demo mode.
# ---------------------------------------------------------------------
check_key() {
    "$VENV_PY" -c "
import os, sys
from dotenv import load_dotenv
load_dotenv()
key = os.environ.get('ANTHROPIC_API_KEY', '').strip()
fake = os.environ.get('TAILORED_FAKE', '')
sys.exit(0 if (key or fake == '1') else 1)
"
}

if check_key; then
    HAVE_KEY=1
else
    HAVE_KEY=0
fi

if [ "$HAVE_KEY" = "0" ] && [ ! -f ".env" ] && [ -f ".env.example" ]; then
    cp ".env.example" ".env"
fi

if [ "$SETUP_ONLY" = "1" ]; then
    echo "Setup complete."
    exit 0
fi

# Non-interactive terminals (CI, piped input, etc.) skip the menu and
# just launch with whatever key/demo state is already present.
if [ "$HAVE_KEY" = "0" ] && [ -t 0 ]; then
    ATTEMPTS=0
    while [ "$HAVE_KEY" = "0" ]; do
        echo ""
        echo "No Anthropic API key found yet."
        echo "  [1] Add my Anthropic API key now (opens \${EDITOR:-nano})"
        echo "  [2] Try it in demo mode (no key needed, sample data)"
        echo "  [3] Exit"
        read -r -p "Choose 1, 2, or 3: " CHOICE
        case "$CHOICE" in
            1)
                "${EDITOR:-nano}" ".env"
                if check_key; then
                    HAVE_KEY=1
                else
                    ATTEMPTS=$((ATTEMPTS + 1))
                    if [ "$ATTEMPTS" -ge 2 ]; then
                        echo ""
                        echo "Still no key found - starting in demo mode instead."
                        export TAILORED_FAKE=1
                        HAVE_KEY=1
                    fi
                fi
                ;;
            2)
                export TAILORED_FAKE=1
                HAVE_KEY=1
                ;;
            3)
                exit 0
                ;;
            *)
                echo "Please enter 1, 2, or 3."
                ;;
        esac
    done
fi

# ---------------------------------------------------------------------
# 6. Launch.
# ---------------------------------------------------------------------
echo ""
echo "Starting Tailored..."
exec "$VENV_PY" run.py

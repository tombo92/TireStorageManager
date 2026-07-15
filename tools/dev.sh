#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────
# TireStorageManager – dev quick-start
#
# Creates / activates the venv, installs all requirements,
# and starts the Flask dev server with live-reload — or
# launches the Installer GUI in UI-dev mode (no real OS
# actions, no admin rights required).
#
# Usage:
#   bash tools/dev.sh                   # Flask app dev server
#   bash tools/dev.sh --installer-ui    # Installer GUI in UI-dev mode
#   bash tools/dev.sh --check-update    # Print update-check JSON and exit
# ─────────────────────────────────────────────────────────
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
VENV_DIR="$REPO_ROOT/.venv"

MODE="app"   # default mode

for arg in "$@"; do
    case "$arg" in
        --installer-ui)  MODE="installer-ui" ;;
        --check-update)  MODE="check-update" ;;
        -h|--help)
            echo "Usage: bash tools/dev.sh [--installer-ui | --check-update]"
            echo ""
            echo "  (default)         Start Flask dev server with live-reload"
            echo "  --installer-ui    Open Installer GUI in UI-dev mode"
            echo "                    (no admin, no real OS changes)"
            echo "  --check-update    Print update-check JSON and exit"
            exit 0
            ;;
    esac
done

echo "──────────────────────────────────────"
echo " TireStorageManager – Dev Environment"
echo "──────────────────────────────────────"

# 1. Create venv if it doesn't exist
if [ ! -d "$VENV_DIR" ]; then
    echo "⏳ Creating virtual environment …"
    python -m venv "$VENV_DIR"
    echo "   ✓ venv created at $VENV_DIR"
fi

# 2. Activate venv
# shellcheck disable=SC1091
if [ -f "$VENV_DIR/Scripts/activate" ]; then
    # Windows (Git Bash / MSYS2)
    source "$VENV_DIR/Scripts/activate"
elif [ -f "$VENV_DIR/bin/activate" ]; then
    # Linux / macOS
    source "$VENV_DIR/bin/activate"
else
    echo "❌ Could not find venv activate script." >&2
    exit 1
fi
echo "   ✓ venv activated ($(python --version))"

# 3. Install / update dependencies
echo "⏳ Installing requirements …"
cd "$REPO_ROOT"
python -m pip install --upgrade pip --quiet
pip install -e "." --quiet
pip install -e ".[test]" --quiet
echo "   ✓ All requirements installed"

# ─────────────────────────────────────────────────────────
# Mode dispatch
# ─────────────────────────────────────────────────────────
if [ "$MODE" = "installer-ui" ]; then
    echo ""
    echo "🛠  Launching Installer GUI in UI-dev mode …"
    echo "   All install / uninstall steps are simulated."
    echo "   No admin rights required.  No real OS changes."
    echo "──────────────────────────────────────"
    # cd is already set to REPO_ROOT; run as a module so Python resolves
    # the installer package from the current directory.
    python -m installer.TSMInstaller --ui-dev
    exit $?
fi

if [ "$MODE" = "check-update" ]; then
    echo ""
    echo "🔍 Checking for updates (via GitHub Releases API) …"
    echo "──────────────────────────────────────"
    python - <<'PYEOF'
import json
from installer.installer_logic import fetch_update_info
try:
    from config import VERSION
except Exception:
    VERSION = "0.0.0"
info = fetch_update_info(VERSION)
print(json.dumps(info, indent=2, ensure_ascii=False))
PYEOF
    exit $?
fi

# 4. Start dev server (default mode)
echo ""
echo "🚀 Starting dev server …"
echo "   Press Ctrl+C to stop."
echo "──────────────────────────────────────"
python "$REPO_ROOT/run.py" --dev

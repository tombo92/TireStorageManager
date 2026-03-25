#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────
# TireStorageManager – dev quick-start
#
# Creates / activates the venv, installs all requirements,
# and starts the Flask dev server with live-reload.
#
# Usage:   bash tools/dev.sh
# ─────────────────────────────────────────────────────────
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
VENV_DIR="$REPO_ROOT/.venv"

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
python -m pip install --upgrade pip --quiet
pip install -r "$REPO_ROOT/requirements.txt" --quiet
if [ -f "$REPO_ROOT/requirements-test.txt" ]; then
    pip install -r "$REPO_ROOT/requirements-test.txt" --quiet
fi
echo "   ✓ All requirements installed"

# 4. Start dev server
echo ""
echo "🚀 Starting dev server …"
echo "   Press Ctrl+C to stop."
echo "──────────────────────────────────────"
python "$REPO_ROOT/run.py" --dev
